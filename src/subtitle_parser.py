"""
字幕解析模块
支持 SRT 和 ASS 格式的双语字幕解析
"""
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import pysubs2


@dataclass
class Segment:
    """单句字幕段落"""
    id: int
    start_time: float  # 秒
    end_time: float    # 秒
    duration: float    # 秒
    source_text: str   # 原文（韩文/英文）
    target_text: str   # 译文（中文）
    
    # 处理状态
    ref_audio_path: Optional[str] = None
    output_audio_path: Optional[str] = None
    actual_duration: Optional[float] = None
    status: str = "pending"  # pending, processing, success, error
    error_msg: Optional[str] = None
    
    def to_dict(self) -> dict:
        """转换为字典，用于 JSON 序列化"""
        return {
            "id": self.id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "source_text": self.source_text,
            "target_text": self.target_text,
            "ref_audio_path": self.ref_audio_path,
            "output_audio_path": self.output_audio_path,
            "actual_duration": self.actual_duration,
            "status": self.status,
            "error_msg": self.error_msg
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Segment":
        """从字典创建"""
        return cls(**data)


class SubtitleParser:
    """字幕解析器"""
    
    def __init__(self):
        # 用于检测中文的正则
        self.chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
        # 用于检测各种括号内容（环境音、注释等）
        # 包括 (), [], {}, （）, 【】 以及音符 ♪
        # 注意：不过滤《》书名号，其内容通常有原配音
        self.bracket_pattern = re.compile(r'([\(\[\{（【].*?[\)\]\}）】])|(♪.*?♪)|(♪+)')
    
    def _clean_text(self, text: str) -> str:
        """清理内容，移除括号内容和多余空白"""
        if not text:
            return ""
        # 移除中英括号及其内部内容，移除音符及其包裹内容
        text = self.bracket_pattern.sub("", text)
        return text.strip()

    def _convert_numbers(self, text: str) -> str:
        """将阿拉伯数字转换为中文读法，避免 TTS 乱读"""
        # 1. 百分比: 50% → 百分之五十
        text = re.sub(r'(\d+\.?\d*)%', lambda m: '百分之' + self._num_to_cn(m.group(1)), text)
        # 2. 年份 (4位数+年): 2025年 → 二零二五年
        text = re.sub(r'(\d{4})年', lambda m: self._digits_to_cn(m.group(1)) + '年', text)
        # 3. 长数字 (5位+): 逐位读
        text = re.sub(r'\d{5,}', lambda m: self._digits_to_cn(m.group(0)), text)
        # 4. 剩余数字: 量词读法 (100 → 一百)
        text = re.sub(r'\d+\.?\d*', lambda m: self._num_to_cn(m.group(0)), text)
        return text

    def _digits_to_cn(self, s: str) -> str:
        """逐位读: 2025 → 二零二五"""
        d = '零一二三四五六七八九'
        return ''.join(d[int(c)] for c in s)

    def _num_to_cn(self, s: str) -> str:
        """量词读: 100 → 一百, 3.5 → 三点五"""
        if '.' in s:
            integer_part, decimal_part = s.split('.', 1)
            return self._int_to_cn(int(integer_part)) + '点' + self._digits_to_cn(decimal_part)
        return self._int_to_cn(int(s))

    def _int_to_cn(self, n: int) -> str:
        """整数转中文量词读法"""
        if n == 0:
            return '零'
        d = '零一二三四五六七八九'
        result = ''
        # 亿
        if n >= 100000000:
            result += self._int_to_cn(n // 100000000) + '亿'
            n %= 100000000
            if 0 < n < 10000000:
                result += '零'
        # 万
        if n >= 10000:
            result += self._int_to_cn(n // 10000) + '万'
            n %= 10000
            if 0 < n < 1000:
                result += '零'
        # 千
        if n >= 1000:
            result += d[n // 1000] + '千'
            n %= 1000
            if 0 < n < 100:
                result += '零'
        # 百
        if n >= 100:
            result += d[n // 100] + '百'
            n %= 100
            if 0 < n < 10:
                result += '零'
        # 十
        if n >= 10:
            if n // 10 == 1 and not result:
                result += '十'
            else:
                result += d[n // 10] + '十'
            n %= 10
        # 个位
        if n > 0:
            result += d[n]
        return result

    def load(self, subtitle_path: str, 
             start_time: float = 0, 
             end_time: float = float('inf'),
             max_segments: int = None) -> list[Segment]:
        """
        加载并解析字幕文件
        已优化：全源语言支持，仅以中文作为配音目标。
        """
        subs = pysubs2.load(subtitle_path, encoding="utf-8")
        
        # 按时间排序
        subs.sort()
        
        segments = []
        segment_id = 1
        
        i = 0
        while i < len(subs):
            line = subs[i]
            start = line.start / 1000.0
            end = line.end / 1000.0
            
            # 过滤时间范围
            if start < start_time:
                i += 1
                continue
            if start >= end_time:
                break
            
            # 基础清理
            text = line.plaintext.strip()
            if not text:
                i += 1
                continue

            # ---- 内联双语处理 (ASS 格式: "中文\N{\rEng}韩文" → plaintext 含 \n) ----
            if '\n' in text:
                parts = [p.strip() for p in text.split('\n') if p.strip()]
                cn_parts = []
                other_parts = []
                for part in parts:
                    cleaned_part = self._clean_text(part)
                    if not cleaned_part:
                        continue
                    if self.chinese_pattern.search(cleaned_part):
                        cn_parts.append(cleaned_part)
                    else:
                        other_parts.append(cleaned_part)

                target_text = ' '.join(cn_parts)
                source_text = ' '.join(other_parts)

                if not target_text.strip():
                    i += 1
                    continue

                # 仅对确认的中文文本转换数字为中文读法
                target_text = self._convert_numbers(target_text)

                segment = Segment(
                    id=segment_id,
                    start_time=start,
                    end_time=end,
                    duration=end - start,
                    source_text=source_text,
                    target_text=target_text
                )
                segments.append(segment)
                segment_id += 1
                i += 1

                if max_segments and len(segments) >= max_segments:
                    break
                continue
            # ---- 内联双语处理结束 ----

            # 应用括号和音符过滤
            cleaned_text = self._clean_text(text)
            
            # 获取纯文本信息以供配对判断
            is_chinese = bool(self.chinese_pattern.search(cleaned_text))
            
            source_text = ""
            target_text = ""
            
            # 尝试查找配对 (同一时间点的另一条字幕)
            paired = False
            if i + 1 < len(subs):
                next_line = subs[i + 1]
                next_start = next_line.start / 1000.0
                next_text = next_line.plaintext.strip()
                
                # 判断是否是同一时间段的双语字幕
                if abs(next_start - start) < 0.01 and next_text:
                    next_cleaned = self._clean_text(next_text)
                    next_is_chinese = bool(self.chinese_pattern.search(next_cleaned))
                    
                    # 简化逻辑：一中一非中
                    if not is_chinese and next_is_chinese:
                        source_text = cleaned_text
                        target_text = next_cleaned
                        i += 2
                        paired = True
                    elif is_chinese and not next_is_chinese:
                        source_text = next_cleaned
                        target_text = cleaned_text
                        i += 2
                        paired = True
                    elif is_chinese and next_is_chinese:
                        # 两条都是中文（罕见），取第一条
                        source_text = ""
                        target_text = cleaned_text
                        i += 2 # 跳过两条，假设它们是重复的或层叠的
                        paired = True
            
            if not paired:
                # 只有一条或无法配对
                if is_chinese:
                    source_text = ""
                    target_text = cleaned_text
                    i += 1
                else:
                    # 没有中文，则不属于配音目标
                    i += 1
                    continue
            
            # 再次检查最终目标文本是否为空 (移除括号后可能变空)
            if not target_text.strip():
                continue

            # 仅对确认的中文文本转换数字为中文读法
            target_text = self._convert_numbers(target_text)

            # 创建 Segment
            segment = Segment(
                id=segment_id,
                start_time=start,
                end_time=end,
                duration=end - start,
                source_text=source_text,
                target_text=target_text
            )
            segments.append(segment)
            segment_id += 1
            
            # 检查最大数量
            if max_segments and len(segments) >= max_segments:
                break
        
        return segments
    
    def get_video_clip_times(self, segments: list[Segment], padding: float = 2.0) -> tuple[float, float]:
        """
        根据字幕段落计算视频裁剪时间范围
        
        Args:
            segments: 字幕段落列表
            padding: 前后扩展时间（秒）
            
        Returns:
            (start_time, end_time) 元组
        """
        if not segments:
            return (0, 60)
        
        start = max(0, segments[0].start_time - padding)
        end = segments[-1].end_time + padding
        
        return (start, end)


if __name__ == "__main__":
    # 测试
    parser = SubtitleParser()
    segments = parser.load(
        "d:/IndexDub/example/苦尽柑来遇见你KR.E01.2025(李知恩朴宝剑).NF.chs&kor韋家瑤譯.srt",
        start_time=60,
        end_time=120,
        max_segments=5
    )
    
    print(f"解析到 {len(segments)} 个字幕段落:")
    for seg in segments:
        print(f"[{seg.id}] {seg.start_time:.2f}s - {seg.end_time:.2f}s ({seg.duration:.2f}s)")
        print(f"    韩文: {seg.source_text}")
        print(f"    中文: {seg.target_text}")
        print()

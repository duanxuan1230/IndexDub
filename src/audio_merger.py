"""
音频合并模块
按时间戳对齐配音音频，与背景音混流回视频
"""
import subprocess
import shutil
import tempfile
import os
from pathlib import Path
from typing import List

from .config import config
from .subtitle_parser import Segment


class AudioMerger:
    """音频合并器"""
    
    def __init__(self):
        self.ffmpeg = "ffmpeg"
    
    def create_dubbed_track(self, segments: List[Segment], 
                            total_duration: float,
                            output_path: str,
                            time_offset: float = 0) -> str:
        """
        根据时间戳创建配音音轨
        已优化：支持分段合并以解决 Windows 命令行过长的问题 (WinError 206)
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        # 过滤出成功生成的段落
        valid_segments = [
            seg for seg in segments 
            if seg.status == "success" and seg.output_audio_path
        ]
        
        if not valid_segments:
            raise RuntimeError("没有可用的配音段落")
            
        # [Optimization] 分段处理，每组最多 50 个片段，防止 command line too long
        batch_size = 50
        if len(valid_segments) <= batch_size:
            return self._execute_merge(valid_segments, total_duration, str(output), time_offset)
        
        print(f">> 片段较多 ({len(valid_segments)})，进行分组分层合并...")
        
        # [NEW] 清理同名旧 batch 文件，防止复用错误的残留文件
        for old_batch in config.intermediate_dir.glob("batch_*.wav"):
            try: old_batch.unlink()
            except: pass
            
        batch_files = []
        for i in range(0, len(valid_segments), batch_size):
            batch = valid_segments[i:i + batch_size]
            batch_output = config.intermediate_dir / f"batch_{i//batch_size}.wav"
            self._execute_merge(batch, total_duration, str(batch_output), time_offset)
            batch_files.append(batch_output)
            
        # 最后合并所有 batch 文件
        # 这里包装成虚假的 Segment 对象以便复用逻辑，但直接用 _execute_merge 并不完全合适
        # 因为 batch 文件已经是有对应时长的了。我们直接用 amix 即可。
        final_cmd = [self.ffmpeg, "-y"]
        for bf in batch_files:
            final_cmd.extend(["-i", str(bf)])
        
        # 混合所有 batch (它们都已经对齐到视频长度了)
        mix_inputs = "".join([f"[{i}:a]" for i in range(len(batch_files))])
        filter_complex = f"{mix_inputs}amix=inputs={len(batch_files)}:duration=first:dropout_transition=0:normalize=0[aout]"
        
        final_cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-ar", str(config.sample_rate),
            "-ac", "1",
            str(output)
        ])
        
        print(f">> 正在合并最终音轨 ({len(batch_files)} 个中继文件)...")
        result = subprocess.run(final_cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode != 0:
            print(f"FFmpeg stderr: {result.stderr}")
            raise RuntimeError(f"最后合并分段音轨失败")
            
        # 清理临时 batch 文件
        for bf in batch_files:
            try: bf.unlink()
            except: pass
            
        return str(output)

    def _execute_merge(self, segments: List[Segment], total_duration: float, 
                       output_path: str, time_offset: float) -> str:
        """实际执行 FFmpeg 合并操作的私有方法"""
        output = Path(output_path)
        
        # 构建 FFmpeg 复杂滤镜
        inputs = []
        filter_parts = []
        
        # 首先创建一个静音基底
        inputs.extend(["-f", "lavfi", "-t", str(total_duration), 
                      "-i", f"anullsrc=r={config.sample_rate}:cl=mono"])
        
        # 添加每个配音片段作为输入
        for i, seg in enumerate(segments):
            inputs.extend(["-i", seg.output_audio_path])
        
        # 构建延迟滤镜
        delay_outputs = []
        for i, seg in enumerate(segments):
            input_idx = i + 1  # 0 是静音基底
            delay_ms = int((seg.start_time - time_offset) * 1000)
            delay_ms = max(0, delay_ms)
            
            filter_parts.append(
                f"[{input_idx}:a]adelay={delay_ms}|{delay_ms},apad=whole_dur={total_duration}[a{i}]"
            )
            delay_outputs.append(f"[a{i}]")
        
        # 混合所有音频
        mix_inputs = "[0:a]" + "".join(delay_outputs)
        mix_count = len(segments) + 1
        filter_parts.append(
            f"{mix_inputs}amix=inputs={mix_count}:duration=first:dropout_transition=0:normalize=0[aout]"
        )
        
        filter_complex = ";".join(filter_parts)
        
        cmd = [
            self.ffmpeg, "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-ar", str(config.sample_rate),
            "-ac", "1",
            str(output)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode != 0:
            print(f"FFmpeg stderr: {result.stderr}")
            raise RuntimeError(f"FFmpeg 执行合并失败")
            
        return str(output)
    
    def mix_with_bgm(self, dub_track: str, bgm_track: str, 
                     output_path: str, 
                     dub_volume: float = 1.5,
                     bgm_volume: float = 1.0) -> str:
        """
        混合配音音轨和背景音乐
        
        Args:
            dub_track: 配音音轨路径
            bgm_track: 背景音乐路径
            output_path: 输出音频路径
            dub_volume: 配音音量（1.0 = 原音量）
            bgm_volume: 背景音乐音量（1.0 = 原音量）
            
        Returns:
            输出音频路径
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        # 混合配音和背景音
        # inputs=2:duration=first (假设配音轨长度与视频一致)
        # normalize=0: 禁用归一化，防止音量衰减 (重要 fix)
        
        filter_complex = f"[0:a]volume={dub_volume}[dub];[1:a]volume={bgm_volume}[bgm];[dub][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        
        cmd = [
            self.ffmpeg, "-y",
            "-i", dub_track,
            "-i", bgm_track,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-ar", str(config.sample_rate),
            "-ac", "2",  # 混合后输出立体声
            str(output)
        ]
        
        print(f">> 混合配音({dub_volume}x)和背景音({bgm_volume}x)...")
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')

        if result.returncode != 0:
            print(f"FFmpeg stderr: {result.stderr}")
            raise RuntimeError(f"混合音频失败")
        
        print(f">> 混合音频已保存: {output}")
        return str(output)
    
    @staticmethod
    def _merge_mute_regions(regions: list, merge_threshold: float) -> list:
        """
        合并间隔 <= merge_threshold 的相邻静音区域。
        消除连续对话中 gap vocal 的快速抖动。
        """
        if not regions:
            return []
        sorted_regions = sorted(regions, key=lambda r: r[0])
        merged = [sorted_regions[0]]
        for start, end in sorted_regions[1:]:
            prev_start, prev_end = merged[-1]
            if start <= prev_end + merge_threshold:
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))
        return merged

    def _build_trapezoid_expr(self, regions: list, fade_dur: float,
                              total_duration: float) -> str:
        """
        构建平滑梯形音量包络的 FFmpeg 表达式。

        每个静音区域 [S, E] 的梯形：
            clip((t-(S-F))/F, 0, 1) * clip(((E+F)-t)/F, 0, 1)
        组合：volume = 1 - max(所有梯形)
        """
        if not regions:
            return "1"

        trapezoids = []
        for (s, e) in regions:
            fade_in_start = max(0, s - fade_dur)
            fade_out_end = min(total_duration, e + fade_dur)
            actual_fade_in = s - fade_in_start
            actual_fade_out = fade_out_end - e

            # 左侧斜坡（淡入静音）
            if actual_fade_in < 0.001:
                left = "1"
            else:
                left = f"clip((t-{fade_in_start:.4f})/{actual_fade_in:.4f},0,1)"

            # 右侧斜坡（淡出静音）
            if actual_fade_out < 0.001:
                right = "1"
            else:
                right = f"clip(({fade_out_end:.4f}-t)/{actual_fade_out:.4f},0,1)"

            # 组合为单个梯形
            if left == "1" and right == "1":
                trapezoids.append("1")
            elif left == "1":
                trapezoids.append(right)
            elif right == "1":
                trapezoids.append(left)
            else:
                trapezoids.append(f"{left}*{right}")

        # 用嵌套 max(a, b) 组合（FFmpeg max() 仅支持2参数）
        if len(trapezoids) == 1:
            max_expr = trapezoids[0]
        else:
            max_expr = trapezoids[-1]
            for i in range(len(trapezoids) - 2, -1, -1):
                max_expr = f"max({trapezoids[i]},{max_expr})"

        return f"1-{max_expr}"

    def create_gap_vocal_track(self, vocal_path: str, segments: List[Segment],
                               total_duration: float, output_path: str,
                               time_offset: float = 0) -> str:
        """
        从原始人声轨道生成间隙音频（平滑包络版）。

        使用梯形音量包络平滑过渡，相邻配音片段合并为连续静音区域，
        消除连续对话中 gap vocal 的"呼吸感"割裂。

        Args:
            vocal_path: 原始人声轨道路径
            segments: 字幕段落列表
            total_duration: 总时长（秒）
            output_path: 输出路径
            time_offset: 时间偏移（裁剪起点）

        Returns:
            输出音频路径
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        # 收集所有成功配音的时间段
        valid_segments = [
            s for s in segments
            if s.status == "success" and s.output_audio_path
        ]

        if not valid_segments:
            shutil.copy(vocal_path, str(output))
            return str(output)

        # 构建原始静音区域（每段前后加小量安全余量）
        safety_margin = 0.03  # 30ms（淡变已处理边界，余量可减小）
        raw_regions = []
        for seg in valid_segments:
            start = seg.start_time - time_offset - safety_margin
            dur = seg.actual_duration if seg.actual_duration else seg.duration
            end = seg.start_time - time_offset + dur + safety_margin
            start = max(0, start)
            end = min(total_duration, end)
            if end > start:
                raw_regions.append((start, end))

        if not raw_regions:
            shutil.copy(vocal_path, str(output))
            return str(output)

        # 合并相邻区域，消除连续对话中的快速抖动
        merge_threshold = config.gap_merge_threshold
        merged_regions = self._merge_mute_regions(raw_regions, merge_threshold)

        fade_dur = config.gap_fade_duration

        print(f">> 生成间隙人声轨 ({len(valid_segments)} 个片段 → "
              f"{len(merged_regions)} 个静音区域, "
              f"淡变={fade_dur*1000:.0f}ms, 合并阈值={merge_threshold*1000:.0f}ms)...")

        # 构建平滑音量包络滤镜，写入临时文件通过 -filter_script:a 传递给 FFmpeg
        expr = self._build_trapezoid_expr(merged_regions, fade_dur, total_duration)
        af_filter = f"volume='{expr}':eval=frame"

        fd, filter_script_path = tempfile.mkstemp(
            suffix='.txt', prefix='ffmpeg_filter_',
            dir=str(output.parent))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(af_filter)

            cmd = [
                self.ffmpeg, "-y",
                "-i", vocal_path,
                "-filter_script:a", filter_script_path,
                "-ar", str(config.sample_rate),
                "-ac", "1",
                "-t", str(total_duration),
                str(output)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace')
            if result.returncode != 0:
                print(f"FFmpeg stderr: {result.stderr}")
                raise RuntimeError(f"生成间隙人声轨失败: {result.stderr[:300]}")
        finally:
            if os.path.exists(filter_script_path):
                os.remove(filter_script_path)

        print(f">> 间隙人声轨已保存: {output}")
        return str(output)

    def mix_two_tracks(self, track_a: str, track_b: str, output_path: str,
                       volume_a: float = 1.0, volume_b: float = 1.0) -> str:
        """
        混合两个音轨（单声道输出）
        用于配音轨 + 间隙人声轨合并

        Args:
            track_a: 音轨 A 路径
            track_b: 音轨 B 路径
            output_path: 输出路径
            volume_a: 音轨 A 音量
            volume_b: 音轨 B 音量

        Returns:
            输出音频路径
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        filter_complex = (
            f"[0:a]volume={volume_a}[a];"
            f"[1:a]volume={volume_b}[b];"
            f"[a][b]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )

        cmd = [
            self.ffmpeg, "-y",
            "-i", track_a,
            "-i", track_b,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-ar", str(config.sample_rate),
            "-ac", "1",
            str(output)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
        if result.returncode != 0:
            print(f"FFmpeg stderr: {result.stderr}")
            raise RuntimeError(f"混合音轨失败: {result.stderr[:300]}")

        return str(output)

    def merge_to_video(self, video_path: str, audio_path: str,
                       output_path: str) -> str:
        """
        将音频合并到视频
        
        Args:
            video_path: 视频路径
            audio_path: 音频路径
            output_path: 输出视频路径
            
        Returns:
            输出视频路径
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            self.ffmpeg, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",             # 标准采样率（22050Hz AAC 播放不兼容）
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            "-movflags", "+faststart",  # MP4 兼容性优化
            str(output)
        ]
        
        print(f">> 合并音频到视频...")
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')

        if result.returncode != 0:
            print(f"FFmpeg stderr: {result.stderr}")
            raise RuntimeError(f"合并视频失败")
        
        print(f">> 最终视频已保存: {output}")
        return str(output)


if __name__ == "__main__":
    print("AudioMerger 模块加载正常")

"""
音频处理模块
负责视频音频提取、音频切分、降噪、Padding
"""
import subprocess
import shutil
import time
import json
from pathlib import Path
from typing import Optional

from .config import config
from .subtitle_parser import Segment


class AudioProcessor:
    """音频处理器"""
    
    def __init__(self):
        self.ffmpeg = "ffmpeg"
        self.ffprobe = "ffprobe"
        
        # 验证 FFmpeg 是否可用
        self._check_ffmpeg()
    
    def _check_ffmpeg(self):
        """检查 FFmpeg 是否安装"""
        try:
            result = subprocess.run(
                [self.ffmpeg, "-version"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode != 0:
                raise RuntimeError("FFmpeg 不可用")
            print(">> FFmpeg 已就绪")
        except FileNotFoundError:
            raise RuntimeError("FFmpeg 未安装或未加入环境变量")
    
    def extract_audio(self, video_path: str, output_path: str) -> str:
        """
        从视频中提取音频
        
        Args:
            video_path: 视频文件路径
            output_path: 输出音频路径
            
        Returns:
            输出音频路径
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            self.ffmpeg, "-y",
            "-i", video_path,
            "-vn",  # 不要视频
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            str(output)
        ]
        
        print(f">> 提取音频: {video_path}")
        t0 = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')

        if result.returncode != 0:
            raise RuntimeError(f"提取音频失败: {result.stderr}")

        elapsed = time.time() - t0
        print(f">> 音频已保存: {output} ({elapsed:.1f}s)")
        return str(output)
    
    def clip_video(self, video_path: str, output_path: str, 
                   start_time: float, duration: float) -> str:
        """
        裁剪视频片段
        
        Args:
            video_path: 视频文件路径
            output_path: 输出视频路径
            start_time: 开始时间（秒）
            duration: 持续时间（秒）
            
        Returns:
            输出视频路径
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            self.ffmpeg, "-y",
            "-ss", str(start_time),  # 输入定位（快速 + 时间戳从0开始）
            "-i", video_path,
            "-t", str(duration),
            "-c:v", "copy",          # 复制视频流
            "-c:a", "aac",           # 音频重新编码（避免 seeking 导致的音频丢失）
            "-b:a", "192k",
            "-map", "0:v:0",         # 映射视频流
            "-map", "0:a:0",         # 映射音频流
            str(output)
        ]
        
        print(f">> 裁剪视频: {start_time:.2f}s - {start_time + duration:.2f}s (时长 {duration:.1f}s)")
        t0 = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')

        if result.returncode != 0:
            raise RuntimeError(f"裁剪视频失败: {result.stderr}")

        elapsed = time.time() - t0
        print(f">> 视频片段已保存: {output} ({elapsed:.1f}s)")
        return str(output)
    
    def get_duration(self, media_path: str) -> float:
        """获取媒体文件时长（秒）"""
        cmd = [
            self.ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            media_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode != 0:
            raise RuntimeError(f"获取时长失败: {result.stderr}")
        
        return float(result.stdout.strip())
    
    def process_segment(self, vocal_path: str, segment: Segment, 
                        output_dir: str, time_offset: float = 0) -> str:
        """
        处理单个字幕段落的音频：切分 + 降噪 + Padding
        
        Args:
            vocal_path: 人声音频路径
            segment: 字幕段落
            output_dir: 输出目录
            time_offset: 时间偏移（如果音频是裁剪后的）
            
        Returns:
            处理后的音频路径
        """
        output = Path(output_dir) / f"seg_{segment.id:04d}.wav"
        output.parent.mkdir(parents=True, exist_ok=True)
        
        # 计算实际的开始时间（考虑偏移）
        start = segment.start_time - time_offset
        duration = segment.duration
        
        # 添加少量前后缓冲以避免切断
        buffer = 0.05  # 50ms
        start = max(0, start - buffer)
        duration = duration + buffer * 2
        
        # 构建滤镜链：降噪 + Padding
        # afftdn: FFT 降噪
        # adelay: 添加前置延迟（静音）
        # apad: 末尾填充
        padding_ms = config.padding_ms
        denoise = config.denoise_strength
        
        # 滤镜链：高通 + 降噪 + 淡入淡出（减少 TTS 参考音频的底噪和边界咔嗒）
        filter_chain = (
            f"highpass=f=80,"
            f"afftdn=nr={denoise}:nf=-25,"
            f"afade=t=in:d=0.01,"
            f"areverse,afade=t=in:d=0.01,areverse"
        )
        
        cmd = [
            self.ffmpeg, "-y",
            "-ss", str(start),
            "-t", str(duration),
            "-i", vocal_path,
            "-af", filter_chain,
            "-ar", str(config.sample_rate),
            "-ac", "1",  # 单声道
            str(output)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')

        if result.returncode != 0:
            raise RuntimeError(f"处理音频段落失败: {result.stderr}")
        
        return str(output)
    
    def create_silence(self, output_path: str, duration: float) -> str:
        """
        创建指定时长的静音音频
        
        Args:
            output_path: 输出路径
            duration: 时长（秒）
            
        Returns:
            输出路径
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            self.ffmpeg, "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r={config.sample_rate}:cl=mono",
            "-t", str(duration),
            str(output)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')

        if result.returncode != 0:
            raise RuntimeError(f"创建静音失败: {result.stderr}")
        
        return str(output)
    
    def merge_audio_to_video(self, video_path: str, audio_path: str, 
                              output_path: str) -> str:
        """
        将音频合并到视频
        
        Args:
            video_path: 视频文件路径（带原音频或无音频）
            audio_path: 新音频路径
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
            "-c:v", "copy",  # 视频直接复制
            "-c:a", "aac",   # 音频编码为 AAC
            "-map", "0:v:0",  # 使用第一个输入的视频
            "-map", "1:a:0",  # 使用第二个输入的音频
            "-shortest",
            str(output)
        ]
        
        print(f">> 合并音频到视频...")
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')

        if result.returncode != 0:
            raise RuntimeError(f"合并失败: {result.stderr}")
        
        print(f">> 输出: {output}")
        return str(output)

    def adjust_speed(self, input_path: str, output_path: str, speed: float) -> str:
        """
        调整音频速度 (保持音高)
        
        Args:
            input_path: 输入音频路径
            output_path: 输出音频路径
            speed: 速度倍率 (e.g. 1.0 = 原速, 1.5 = 1.5倍速)
            
        Returns:
            输出音频路径
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        # FFmpeg atempo filter range is 0.5 to 2.0. 
        # For larger changes, we need to chain them, but for dubbing 0.5-2.0 is usually enough.
        speed = max(0.5, min(2.0, speed))
        
        cmd = [
            self.ffmpeg, "-y",
            "-i", input_path,
            "-filter:a", f"atempo={speed}",
            "-vn",
            str(output)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')

        if result.returncode != 0:
            raise RuntimeError(f"调整语速失败: {result.stderr}")
            
        return str(output)

    def post_process_audio(self, input_path: str, output_path: str,
                           speed: float = None, target_lufs: float = -16.0) -> str:
        """
        音频后处理：语速调整 + 音量标准化（两遍 loudnorm）

        Pass 1: 测量实际响度参数
        Pass 2: 使用测量值精确标准化（linear=true 优先线性增益）

        Args:
            input_path: 输入音频路径
            output_path: 输出音频路径
            speed: 速度倍率，None 表示不调速（仅标准化音量）
            target_lufs: 目标响度 (LUFS, EBU R128)

        Returns:
            输出音频路径
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        # 预处理滤镜（两遍都需要，保证测量与实际一致）
        pre_filters = []
        if speed is not None:
            speed = max(0.5, min(2.0, speed))
            pre_filters.append(f"atempo={speed}")
        pre_filters.append("highpass=f=80")

        tp = -2.0   # 折中：比 -3.0 紧（更一致），比 -1.5 松（避免失真）
        lra = 7     # 更窄动态范围，片段间音量更一致

        # ---- Pass 1: 测量响度 ----
        measure_filters = pre_filters + [
            f"loudnorm=I={target_lufs}:TP={tp}:LRA={lra}:print_format=json"
        ]
        cmd_measure = [
            self.ffmpeg, "-y",
            "-i", input_path,
            "-filter:a", ",".join(measure_filters),
            "-f", "null", "-"
        ]
        result = subprocess.run(
            cmd_measure, capture_output=True, text=True,
            encoding='utf-8', errors='replace'
        )
        if result.returncode != 0:
            raise RuntimeError(f"loudnorm 测量失败: {result.stderr[:200]}")

        # 解析 stderr 末尾的 JSON（FFmpeg 将 loudnorm 测量结果输出到 stderr）
        stderr = result.stderr
        json_start = stderr.rfind('{')
        json_end = stderr.rfind('}') + 1
        if json_start < 0 or json_end <= json_start:
            raise RuntimeError("无法从 FFmpeg 输出中解析 loudnorm 测量数据")

        try:
            measured = json.loads(stderr[json_start:json_end])
        except json.JSONDecodeError as e:
            raise RuntimeError(f"loudnorm JSON 解析失败: {e}")

        measured_i = measured['input_i']
        measured_tp = measured['input_tp']
        measured_lra = measured['input_lra']
        measured_thresh = measured['input_thresh']

        # ---- Pass 2: 使用测量值精确标准化 ----
        loudnorm_apply = (
            f"loudnorm=I={target_lufs}:TP={tp}:LRA={lra}"
            f":measured_I={measured_i}:measured_TP={measured_tp}"
            f":measured_LRA={measured_lra}:measured_thresh={measured_thresh}"
            f":linear=true"
        )
        apply_filters = pre_filters + [
            loudnorm_apply,
            "afade=t=in:d=0.02",
            "areverse,afade=t=in:d=0.02,areverse"
        ]
        cmd_apply = [
            self.ffmpeg, "-y",
            "-i", input_path,
            "-filter:a", ",".join(apply_filters),
            "-ar", str(config.sample_rate),
            "-vn",
            str(output)
        ]
        result = subprocess.run(
            cmd_apply, capture_output=True, text=True,
            encoding='utf-8', errors='replace'
        )
        if result.returncode != 0:
            raise RuntimeError(f"音频后处理失败: {result.stderr[:200]}")

        return str(output)

    def separate_audio(self, input_path: str, output_dir: str) -> tuple[str, str]:
        """
        使用 audio-separator 分离人声和伴奏
        
        Args:
            input_path: 输入音频路径
            output_dir: 输出目录
            
        Returns:
            (vocal_path, bgm_path)
        """
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        
        print(f">> 开始音频分离 (UVR5)...")
        print(f"   输入: {input_path}")
        
        # 使用 uv run 调用 audio-separator
        # 注意：audio-separator 默认输出文件名包含 (Vocals)/(Instrumental)
        # 我们使用 MDX-Net 模型: UVR-MDX-NET-Inst_HQ_3.onnx (效果较好)
        
        # [Optimization] 使用本地已下载的模型
        # 我们已经手动下载了 UVR-MDX-NET-Inst_HQ_3.onnx 到 d:\IndexDub\models
        models_dir = Path(config.project_root) / "models"
        
        cmd = [
            "uv", "run", "--with", "audio-separator[gpu,onnxruntime-gpu]", "audio-separator",
            input_path,
            "--output_dir", str(out_path),
            "--model_filename", "UVR-MDX-NET-Inst_HQ_3.onnx",
            "--model_file_dir", str(models_dir),  # 指定本地模型目录
            "--output_format", "wav",
            "--normalization", "0.9"
            # 注意: GPU 通过 audio-separator[gpu] 包自动启用,无需 --device 参数
        ]

        # 使用 Popen 实时转发进度输出（audio-separator 进度信息在 stderr）
        t0 = time.time()
        print(f">> 音频分离进行中，请耐心等待...")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        # 实时读取 stderr
        stderr_lines = []
        for line in process.stderr:
            line = line.rstrip()
            if line:
                print(f"   {line}")
                stderr_lines.append(line)
        process.wait()
        elapsed = time.time() - t0

        if process.returncode != 0:
            error_details = f"Return code: {process.returncode}"
            if stderr_lines:
                error_details += f"\nStderr: {''.join(stderr_lines[-5:])}"
            raise RuntimeError(f"音频分离失败: {error_details}")

        print(f">> 音频分离完成 (耗时 {elapsed:.1f}s)")
            
        # 查找输出文件
        # default output naming: {filename}_(Vocals).wav
        stem = Path(input_path).stem
        
        # 尝试查找可能的输出文件名 (因为 audio-separator 版本不同可能命名略有不同)
        # 我们可以通过列出 output_dir 的文件来匹配
        
        vocals = None
        bgm = None
        
        for f in out_path.iterdir():
            if f.name.startswith(stem):
                if "(Vocals)" in f.name:
                    vocals = str(f)
                elif "(Instrumental)" in f.name:
                    bgm = str(f)
        
        if not vocals or not bgm:
            # Fallback check (sometimes it might not use brackets depending on config, but default is brackets)
            raise RuntimeError(f"未能找到分离后的输出文件. 目录: {output_dir}")
            
        # 重命名为标准名称
        final_vocals = out_path / f"{stem}_vocals.wav"
        final_bgm = out_path / f"{stem}_bgm.wav"
        
        shutil.move(vocals, final_vocals)
        shutil.move(bgm, final_bgm)
        
        print(f">> 分离完成:")
        print(f"   人声: {final_vocals}")
        print(f"   伴奏: {final_bgm}")
        
        return str(final_vocals), str(final_bgm)


if __name__ == "__main__":
    # 测试
    processor = AudioProcessor()
    print("AudioProcessor 模块加载正常")

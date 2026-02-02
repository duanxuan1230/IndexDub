"""
IndexDub 全局配置
"""
import os
import sys
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Config:
    """全局配置类"""
    
    # 项目根目录 (动态获取)
    # 假设 config.py 位于 src/config.py，向前推两级得到项目根目录
    project_root: Path = field(default_factory=lambda: Path(__file__).parent.parent.absolute())
    
    # IndexTTS 配置
    indextts_dir: Path = field(init=False)
    indextts_checkpoint_dir: Path = field(init=False)
    indextts_config: Path = field(init=False)
    
    intermediate_dir: Path = field(init=False)  # [NEW]
    segments_dir: Path = field(init=False)
    output_segments_dir: Path = field(init=False)
    
    # 最终输出目录
    output_dir: Path = field(init=False)
    
    # 音频处理参数
    padding_ms: int = 100  # 音频切片前后的静音padding（毫秒）
    denoise_strength: int = 15  # FFmpeg afftdn 降噪强度 (0-100)
    sample_rate: int = 22050  # IndexTTS2 输出采样率
    
    # IndexTTS2 推理参数
    use_fp16: bool = True  # 使用半精度以降低显存
    use_cuda_kernel: bool = False  # Windows 下禁用 CUDA kernel
    
    # 语速调整参数
    speed_no_adjust_threshold: float = 0.1  # ratio 偏差 <=此值不调整 (0.1 = ±10%)
    speed_min_atempo: float = 0.8           # 最慢 atempo 值（最多减速 20%）
    speed_max_atempo: float = 1.25          # 最快 atempo 值（最多加速 25%）

    # 音量标准化
    target_loudness_lufs: float = -16.0     # 目标响度 (LUFS, EBU R128 语音标准)

    # 间隙人声包络参数
    gap_merge_threshold: float = 0.30       # 合并间隔小于此值的相邻静音区域（秒）
    gap_fade_duration: float = 0.15         # 静音区域边界淡入淡出时长（秒）

    # Demo 配置
    demo_max_segments: int = 5  # Demo 模式最大处理句数
    demo_start_time: float = 60.0  # Demo 开始时间（秒）- 跳过片头
    demo_end_time: float = 120.0  # Demo 结束时间（秒）
    
    def __post_init__(self):
        """初始化依赖路径"""
        # IndexTTS
        self.indextts_dir = self.project_root / "index-tts"
        self.indextts_checkpoint_dir = self.indextts_dir / "checkpoints"
        self.indextts_config = self.indextts_checkpoint_dir / "config.yaml"
        
        # Temp Dirs
        self.temp_dir = self.project_root / "temp"
        self.intermediate_dir = self.temp_dir / "intermediate"
        self.segments_dir = self.temp_dir / "segments"
        self.output_segments_dir = self.temp_dir / "output"
        
        # Output Dir
        self.output_dir = self.project_root / "output"

    def ensure_dirs(self):
        """确保所有目录存在"""
        for path in [self.temp_dir, self.intermediate_dir, 
                     self.segments_dir, self.output_segments_dir, self.output_dir]:
            path.mkdir(parents=True, exist_ok=True)


# 全局配置实例
config = Config()

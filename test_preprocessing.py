"""
IndexDub 预处理测试脚本
测试字幕解析、视频裁剪、音频提取和片段处理
（不含 TTS 配音，用于快速验证流程）
"""
import sys
import io
from pathlib import Path

# Windows 控制台 UTF-8 编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent))

from src.config import config
from src.subtitle_parser import SubtitleParser
from src.audio_processor import AudioProcessor


def test_preprocessing():
    print("=" * 60)
    print("IndexDub 预处理测试")
    print("=" * 60)
    
    # 配置
    video_path = "example/苦尽柑来遇见你01.mp4"
    subtitle_path = "example/苦尽柑来遇见你KR.E01.2025(李知恩朴宝剑).NF.chs&kor韋家瑤譯.srt"
    
    # 确保目录存在
    config.ensure_dirs()
    
    # Step 1: 解析字幕
    print("\n[Step 1] 解析字幕...")
    parser = SubtitleParser()
    segments = parser.load(
        subtitle_path,
        start_time=75,  # 从 1:15 开始
        end_time=100,   # 到 1:40
        max_segments=3
    )
    
    print(f"  解析到 {len(segments)} 个字幕段落:")
    for seg in segments:
        print(f"    [{seg.id}] {seg.start_time:.2f}s - {seg.end_time:.2f}s ({seg.duration:.2f}s)")
        print(f"         原文: {seg.source_text[:20]}...")  # 截断避免编码问题
        print(f"         中文: {seg.target_text}")
    
    if not segments:
        print("  错误: 未找到字幕段落")
        return
    
    # 计算裁剪范围
    clip_start, clip_end = parser.get_video_clip_times(segments, padding=2.0)
    clip_duration = clip_end - clip_start
    print(f"\n  视频裁剪范围: {clip_start:.2f}s - {clip_end:.2f}s ({clip_duration:.2f}s)")
    
    # Step 2: 裁剪视频
    print("\n[Step 2] 裁剪视频...")
    processor = AudioProcessor()
    
    clipped_video = str(config.temp_dir / "test_clip.mp4")
    processor.clip_video(video_path, clipped_video, clip_start, clip_duration)
    
    # Step 3: 提取音频
    print("\n[Step 3] 提取音频...")
    audio_path = str(config.vocals_dir / "test_audio.wav")
    processor.extract_audio(clipped_video, audio_path)
    
    # Step 4: 处理音频片段
    print("\n[Step 4] 处理音频片段...")
    for seg in segments:
        ref_audio = processor.process_segment(
            audio_path, seg, 
            str(config.segments_dir),
            time_offset=clip_start
        )
        seg.ref_audio_path = ref_audio
        print(f"    片段 {seg.id}: {Path(ref_audio).name}")
    
    print("\n" + "=" * 60)
    print("预处理测试完成!")
    print(f"  裁剪视频: {clipped_video}")
    print(f"  提取音频: {audio_path}")
    print(f"  参考片段: {len(segments)} 个")
    print("=" * 60)
    
    print("\n下一步: 运行 main.py 进行完整配音测试")
    print("  python main.py --demo --max-segments 3 --start-time 75 --end-time 100")


if __name__ == "__main__":
    test_preprocessing()

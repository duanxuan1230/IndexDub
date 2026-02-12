"""
IndexDub - AI自动化配音系统
主入口文件
"""
import sys
import io
import argparse
from pathlib import Path

# Windows 控制台 UTF-8 编码
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from src.pipeline import Pipeline
from src.config import config


def main():
    parser = argparse.ArgumentParser(description="IndexDub - AI自动化配音系统")
    
    parser.add_argument(
        "--video", "-v",
        type=str,
        default="example/When.Life.Gives.You.Tangerines.S01E01.DUAL.1080p.WEBRip.x265-KONTRAST.mkv",
        help="视频文件路径"
    )
    
    parser.add_argument(
        "--subtitle", "-s",
        type=str,
        default="example/苦尽柑来遇见你KR.E01.2025(李知恩朴宝剑).NF.chs.srt",
        help="字幕文件路径"
    )
    
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出目录"
    )
    
    parser.add_argument(
        "--demo",
        action="store_true",
        default=True,
        help="Demo 模式（只处理部分片段）"
    )
    
    parser.add_argument(
        "--full",
        action="store_true",
        help="完整处理模式"
    )
    
    parser.add_argument(
        "--max-segments",
        type=int,
        default=5,
        help="Demo 模式最大处理句数"
    )
    
    parser.add_argument(
        "--start-time",
        type=float,
        default=60.0,
        help="Demo 模式开始时间（秒）"
    )
    
    parser.add_argument(
        "--end-time",
        type=float,
        default=180.0,
        help="Demo 模式结束时间（秒）"
    )
    
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制从头开始（忽略已完成的状态和文件）"
    )

    parser.add_argument(
        "--batch",
        action="store_true",
        help="批处理模式: 读取 input/batch.json 逐集处理"
    )
    
    args = parser.parse_args()

    project_root = Path(__file__).parent

    # 更新 Demo 配置
    demo_mode = not args.full
    if demo_mode:
        config.demo_max_segments = args.max_segments
        config.demo_start_time = args.start_time
        config.demo_end_time = args.end_time

    # 批处理模式
    if args.batch:
        from src.batch_runner import BatchRunner

        batch_json = project_root / "input" / "batch.json"
        if not batch_json.exists():
            print(f"错误: 未找到 {batch_json}")
            print(f"\n请创建 input/batch.json，格式示例:")
            print('''{
  "entries": [
    {
      "video": "input/EP01.mkv",
      "subtitle": "input/EP01.chs.srt",
      "status": "pending",
      "output": null,
      "error": null
    }
  ]
}''')
            sys.exit(1)

        runner = BatchRunner(
            batch_json_path=str(batch_json),
            demo_mode=demo_mode,
            force_run=args.force
        )
        runner.run()
        return

    # 单集模式
    video_path = project_root / args.video
    subtitle_path = project_root / args.subtitle

    if not video_path.exists():
        print(f"错误: 视频文件不存在: {video_path}")
        sys.exit(1)

    if not subtitle_path.exists():
        print(f"错误: 字幕文件不存在: {subtitle_path}")
        sys.exit(1)

    pipeline = Pipeline(
        video_path=str(video_path),
        subtitle_path=str(subtitle_path),
        output_dir=args.output,
        demo_mode=demo_mode,
        force_run=args.force
    )

    try:
        output_video = pipeline.run()
        print(f"\n成功! 输出文件: {output_video}")

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

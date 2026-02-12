"""
批量处理模块
读取 input/batch.json，逐集执行配音流程，TTS 模型跨集复用
"""
import json
import time
import traceback
from pathlib import Path

from .config import config
from .pipeline import Pipeline
from .tts_engine import TTSEngine


class BatchRunner:
    """批量配音控制器"""

    def __init__(self, batch_json_path: str, demo_mode: bool = True,
                 force_run: bool = False):
        self.batch_path = Path(batch_json_path)
        self.demo_mode = demo_mode
        self.force_run = force_run
        self.entries = []

    def load(self):
        """读取 batch.json"""
        with open(self.batch_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.entries = data.get("entries", [])

    def save(self):
        """写回 batch.json"""
        with open(self.batch_path, 'w', encoding='utf-8') as f:
            json.dump({"entries": self.entries}, f,
                      ensure_ascii=False, indent=2)

    def run(self):
        """处理所有待处理的条目"""
        self.load()

        if not self.entries:
            print("batch.json 中没有条目，无需处理。")
            return

        # 筛选待处理条目
        if self.force_run:
            to_process = list(enumerate(self.entries))
        else:
            to_process = [
                (i, e) for i, e in enumerate(self.entries)
                if e.get("status") in ("pending", "error", "processing")
            ]

        if not to_process:
            print("所有条目已完成，无需处理。如需重新处理，请将 status 改为 pending 或使用 --force。")
            return

        total = len(self.entries)
        count = len(to_process)
        print(f"\n批处理: 共 {total} 条，本次处理 {count} 条")
        print(f"模式: {'完整' if not self.demo_mode else 'Demo'}"
              f"{' (强制重跑)' if self.force_run else ''}")

        # 加载共享 TTS 引擎（一次加载，所有集复用）
        tts_engine = TTSEngine(lazy_load=True)
        t_start = time.time()

        try:
            for seq, (idx, entry) in enumerate(to_process):
                video_rel = entry.get("video", "")
                subtitle_rel = entry.get("subtitle", "")
                video_path = config.project_root / video_rel
                subtitle_path = config.project_root / subtitle_rel

                print(f"\n{'='*60}")
                print(f"[{seq+1}/{count}] {video_rel}")
                print(f"{'='*60}")

                # 验证文件存在
                if not video_path.exists():
                    entry["status"] = "error"
                    entry["error"] = f"视频文件不存在: {video_path}"
                    print(f"  错误: {entry['error']}")
                    self.save()
                    continue
                if not subtitle_path.exists():
                    entry["status"] = "error"
                    entry["error"] = f"字幕文件不存在: {subtitle_path}"
                    print(f"  错误: {entry['error']}")
                    self.save()
                    continue

                # 标记为处理中
                entry["status"] = "processing"
                entry["error"] = None
                self.save()

                try:
                    pipeline = Pipeline(
                        video_path=str(video_path),
                        subtitle_path=str(subtitle_path),
                        demo_mode=self.demo_mode,
                        force_run=self.force_run,
                        tts_engine=tts_engine
                    )
                    output_video = pipeline.run()
                    entry["status"] = "completed"
                    entry["output"] = output_video
                    entry["error"] = None
                    print(f"\n  完成: {output_video}")

                except Exception as e:
                    traceback.print_exc()
                    entry["status"] = "error"
                    entry["error"] = str(e)
                    print(f"\n  失败: {e}")

                self.save()

        finally:
            tts_engine.unload()

        # 汇总
        elapsed = time.time() - t_start
        completed = sum(1 for e in self.entries if e["status"] == "completed")
        errors = sum(1 for e in self.entries if e["status"] == "error")
        pending = sum(1 for e in self.entries if e["status"] in ("pending", "processing"))

        print(f"\n{'='*60}")
        print(f"批处理完成 ({elapsed/60:.1f} 分钟)")
        print(f"  成功: {completed}  失败: {errors}  待处理: {pending}")
        print(f"  状态已保存至: {self.batch_path}")
        print(f"{'='*60}")

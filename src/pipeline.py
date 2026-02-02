"""
主流程控制器
串联所有模块，实现完整的配音工作流
"""
import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List

from .config import config
from .subtitle_parser import SubtitleParser, Segment
from .audio_processor import AudioProcessor
from .tts_engine import TTSEngine
from .audio_merger import AudioMerger


@dataclass
class ProjectManifest:
    """项目状态记录"""
    project_name: str
    video_source: str
    subtitle_source: str
    status: str = "pending"  # pending, processing, completed, error
    
    # 处理后的文件
    clipped_video: Optional[str] = None
    vocal_track: Optional[str] = None
    bgm_track: Optional[str] = None
    dubbed_track: Optional[str] = None
    final_video: Optional[str] = None
    
    # 阶段状态跟踪 (Double Verification)
    # 格式: {stage_name: "completed" | "pending"}
    # 文件验证从顶层字段（clipped_video 等）和 segments 派生，不再冗余存储
    stages_status: dict = field(default_factory=lambda: {
        "parse": "pending",
        "clip": "pending",
        "extract": "pending",
        "process": "pending",
        "generate": "pending",
        "merge": "pending"
    })
    
    # 时间范围
    clip_start: float = 0
    clip_end: float = 0
    
    # 段落列表
    segments: List[Segment] = field(default_factory=list)
    
    # 错误信息
    error_msg: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "video_source": self.video_source,
            "subtitle_source": self.subtitle_source,
            "status": self.status,
            "clipped_video": self.clipped_video,
            "vocal_track": self.vocal_track,
            "bgm_track": self.bgm_track,
            "dubbed_track": self.dubbed_track,
            "final_video": self.final_video,
            "clip_start": self.clip_start,
            "clip_end": self.clip_end,
            "stages_status": self.stages_status,
            "segments": [seg.to_dict() for seg in self.segments],
            "error_msg": self.error_msg
        }
    
    def save(self, path: str):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load(cls, path: str) -> "ProjectManifest":
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        segments = [Segment.from_dict(s) for s in data.pop('segments', [])]

        # 旧格式兼容：将 {"status": "completed", "files": [...]} 转为 "completed"
        stages = data.get('stages_status', {})
        for stage_name, stage_val in stages.items():
            if isinstance(stage_val, dict):
                stages[stage_name] = stage_val.get("status", "pending")

        manifest = cls(**{k: v for k, v in data.items() if k != 'segments'})
        manifest.segments = segments
        return manifest


class Pipeline:
    """主流程控制器"""
    
    def __init__(self, video_path: str, subtitle_path: str, 
                 output_dir: str = None, project_name: str = None,
                 demo_mode: bool = True, force_run: bool = False):
        """
        初始化流程控制器
        
        Args:
            video_path: 视频文件路径
            subtitle_path: 字幕文件路径
            output_dir: 输出目录
            project_name: 项目名称
            demo_mode: 是否为 Demo 模式（只处理部分片段）
            force_run: 是否强制重新运行
        """
        self.video_path = Path(video_path)
        self.subtitle_path = Path(subtitle_path)
        self.output_dir = Path(output_dir) if output_dir else config.output_dir
        self.demo_mode = demo_mode
        self.force_run = force_run
        
        # 项目名称
        if project_name:
            self.project_name = project_name
        else:
            self.project_name = self.video_path.stem
        
        # Manifest 保存路径
        self.manifest_path = config.temp_dir / f"{self.project_name}_manifest.json"
        
        # 尝试加载已有状态
        if self.force_run:
            print(f"  [Force Run] 强制重跑模式已开启")

            # 清理项目相关的所有中间文件
            self._clean_intermediate_files()

            # 创建全新的 manifest
            self.manifest = ProjectManifest(
                project_name=self.project_name,
                video_source=str(self.video_path),
                subtitle_source=str(self.subtitle_path)
            )
            print(f"  已重置项目状态并清理中间文件")
        elif self.manifest_path.exists():
            try:
                self.manifest = ProjectManifest.load(str(self.manifest_path))
                print(f"  已从 {self.manifest_path} 加载现有状态")
            except Exception as e:
                print(f"  警告: 加载进度失败 ({e})，将重新开始")
                self.manifest = ProjectManifest(
                    project_name=self.project_name,
                    video_source=str(self.video_path),
                    subtitle_source=str(self.subtitle_path)
                )
        else:
            self.manifest = ProjectManifest(
                project_name=self.project_name,
                video_source=str(self.video_path),
                subtitle_source=str(self.subtitle_path)
            )
        
        # 初始化组件
        self.subtitle_parser = SubtitleParser()
        self.audio_processor = AudioProcessor()
        self.tts_engine = None  # 延迟加载
        self.audio_merger = AudioMerger()
        
        # 确保目录存在
        config.ensure_dirs()
    
    def save_manifest(self):
        """保存项目状态"""
        self.manifest.save(str(self.manifest_path))

    def _clean_intermediate_files(self):
        """
        清理项目相关的所有中间文件
        警告: 此操作不可恢复，仅在 force_run=True 时调用
        """
        cleaned_files = []
        cleaned_dirs = []

        try:
            # 1. 删除 manifest 文件
            if self.manifest_path.exists():
                self.manifest_path.unlink()
                cleaned_files.append(self.manifest_path.name)

            # 2. 删除 temp 根目录的项目文件
            for pattern in [f"{self.project_name}_*.wav", f"{self.project_name}_*.mp4"]:
                for file in config.temp_dir.glob(pattern):
                    file.unlink()
                    cleaned_files.append(file.name)

            # 3. 清理 intermediate 目录
            if config.intermediate_dir.exists():
                for pattern in [f"{self.project_name}_*"]:
                    for file in config.intermediate_dir.glob(pattern):
                        file.unlink()
                        cleaned_files.append(f"intermediate/{file.name}")

            # 4. 清理 segments 目录 (所有 seg_*.wav 和 ref_*.wav)
            if config.segments_dir.exists():
                count = 0
                for pattern in ["seg_*.wav", "ref_*.wav"]:
                    for file in config.segments_dir.glob(pattern):
                        file.unlink()
                        count += 1
                if count > 0:
                    cleaned_dirs.append(f"segments/ ({count} 个音频片段)")

            # 5. 清理 output 目录 (所有 dub_*.wav)
            if config.output_segments_dir.exists():
                count = 0
                for pattern in ["dub_*.wav", "dub_*_adj.wav"]:
                    for file in config.output_segments_dir.glob(pattern):
                        file.unlink()
                        count += 1
                if count > 0:
                    cleaned_dirs.append(f"output/ ({count} 个配音片段)")

            # 打印清理日志
            if cleaned_files or cleaned_dirs:
                print(f"  已清理中间文件:")
                for f in cleaned_files[:5]:  # 最多显示5个文件
                    print(f"    - {f}")
                if len(cleaned_files) > 5:
                    print(f"    ... 及其他 {len(cleaned_files)-5} 个文件")
                for d in cleaned_dirs:
                    print(f"    - {d}")

        except PermissionError as e:
            print(f"  ⚠ 警告: 部分文件无法删除 (文件被占用): {e}")
            print(f"  提示: 请关闭可能占用文件的程序 (如视频播放器、音频编辑器)")
        except Exception as e:
            print(f"  ⚠ 警告: 清理中间文件时发生错误: {e}")
            print(f"  程序将继续运行，但可能会使用部分旧文件")

    def _is_stage_completed(self, stage_name: str) -> bool:
        """检查某个阶段是否已完成（状态 + 物理文件双重验证）"""
        status = self.manifest.stages_status.get(stage_name)
        if isinstance(status, dict):  # 兼容旧格式 {"status": "...", "files": [...]}
            status = status.get("status", "pending")
        if status != "completed":
            return False

        # 从顶层字段派生需要验证的文件
        if stage_name == "clip":
            return bool(self.manifest.clipped_video and Path(self.manifest.clipped_video).exists())
        elif stage_name == "extract":
            return bool(self.manifest.vocal_track and Path(self.manifest.vocal_track).exists())
        elif stage_name == "merge":
            return bool(self.manifest.final_video and Path(self.manifest.final_video).exists())
        return True  # parse, process, generate 不需要在此处验证文件

    def _invalidate_on_range_change(self):
        """检测时间范围变化，自动清理过期的中间文件（如 demo→full 切换）"""
        if not self.manifest.clipped_video or not Path(self.manifest.clipped_video).exists():
            return  # 无旧裁剪，无需检测

        expected_duration = self.manifest.clip_end - self.manifest.clip_start
        try:
            actual_duration = self.audio_processor.get_duration(self.manifest.clipped_video)
        except Exception:
            return

        # 允许 2 秒容差（padding 和编码差异）
        if abs(actual_duration - expected_duration) <= 2.0:
            return  # 时间范围未变，无需处理

        print(f"\n  ⚠ 检测到时间范围变更（旧裁剪: {actual_duration:.1f}s, 新需求: {expected_duration:.1f}s）")
        print(f"  自动清理过期的中间文件...")

        # 删除旧的裁剪视频和音频分离结果
        for path_str in [self.manifest.clipped_video, self.manifest.vocal_track, self.manifest.bgm_track]:
            if path_str and Path(path_str).exists():
                Path(path_str).unlink()
                print(f"    - 已删除: {Path(path_str).name}")

        # 删除 full.wav 中间文件（提取的完整音频）
        full_audio = config.intermediate_dir / f"{self.project_name}_full.wav"
        if full_audio.exists():
            full_audio.unlink()
            print(f"    - 已删除: {full_audio.name}")

        # 重置相关阶段状态
        self.manifest.clipped_video = None
        self.manifest.vocal_track = None
        self.manifest.bgm_track = None
        self.manifest.stages_status["clip"] = "pending"
        self.manifest.stages_status["extract"] = "pending"
        self.manifest.stages_status["process"] = "pending"
        self.manifest.stages_status["generate"] = "pending"

        # 清理所有 segment 文件和状态（ref 音频已失效）
        for seg in self.manifest.segments:
            seg.ref_audio_path = None
            seg.output_audio_path = None
            seg.actual_duration = None
            if seg.status != "pending":
                seg.status = "pending"
                seg.error_msg = None

        # 清理 segments 和 output 目录的文件
        if config.segments_dir.exists():
            for f in config.segments_dir.glob("seg_*.wav"):
                f.unlink()
            for f in config.segments_dir.glob("ref_*.wav"):
                f.unlink()
        if config.output_segments_dir.exists():
            for f in config.output_segments_dir.glob("dub_*.wav"):
                f.unlink()

        self.save_manifest()
        print(f"  已重置 Stage 2-6，将从裁剪开始重新处理")

    def run(self) -> str:
        """
        运行完整配音流程
        已优化: 实现全流程断点续传
        """
        try:
            self.manifest.status = "processing"
            self.save_manifest()
            
            print("=" * 60)
            print(f"IndexDub - AI自动化配音系统")
            print(f"项目: {self.project_name}")
            print(f"模式: {'Demo (仅处理部分片段)' if self.demo_mode else '完整处理'}")
            print("=" * 60)
            
            # Stage 1: 解析字幕
            self._stage_parse_subtitles()

            # 检测时间范围变化（如 demo→full 切换），自动清理过期中间文件
            self._invalidate_on_range_change()

            # Stage 2: 裁剪视频
            if self._is_stage_completed("clip"):
                print("\n[Stage 2/6] 跳过裁剪视频 (已通过双重验证)")
            else:
                self._stage_clip_video()
            
            # Stage 3: 提取音频
            if self._is_stage_completed("extract"):
                print("\n[Stage 3/6] 跳过提取音频 (已通过双重验证)")
            else:
                self._stage_extract_audio()
            
            # Stage 4: 处理音频片段
            self._stage_process_segments()
            
            # Stage 5: 生成配音
            self._stage_generate_dubbing()
            
            # Stage 6: 合并导出
            self._stage_merge_output()
            
            self.manifest.status = "completed"
            self.save_manifest()
            
            print("=" * 60)
            print("✓ 配音完成!")
            print(f"输出文件: {self.manifest.final_video}")
            print("=" * 60)
            
            return self.manifest.final_video
            
        except Exception as e:
            self.manifest.status = "error"
            self.manifest.error_msg = str(e)
            self.save_manifest()
            raise
        
        finally:
            # 清理 TTS 引擎
            if self.tts_engine:
                self.tts_engine.unload()
    
    def _stage_parse_subtitles(self):
        """Stage 1: 解析字幕"""
        print("\n[Stage 1/6] 解析字幕...")
        
        # 记录旧片段状态以供恢复
        old_segments = {
            (s.start_time, s.target_text): s 
            for s in self.manifest.segments 
            if s.status == "success"
        }
        
        if self.demo_mode:
            start_time = config.demo_start_time
            end_time = config.demo_end_time
            max_segments = config.demo_max_segments
            
            new_segments = self.subtitle_parser.load(
                str(self.subtitle_path),
                start_time=start_time,
                end_time=end_time,
                max_segments=max_segments
            )
            clip_start, clip_end = self.subtitle_parser.get_video_clip_times(new_segments)
        else:
            # 完整模式：0秒起点，全视频终点
            start_time = 0
            max_segments = None
            
            new_segments = self.subtitle_parser.load(
                str(self.subtitle_path),
                start_time=0,
                max_segments=None
            )
            
            # 获取视频完整时长
            full_duration = self.audio_processor.get_duration(str(self.video_path))
            clip_start = 0
            clip_end = full_duration
        
        if not new_segments:
            raise RuntimeError("未找到有效的字幕段落")
        
        # 恢复状态逻辑
        merged_count = 0
        for ns in new_segments:
            key = (ns.start_time, ns.target_text)
            if key in old_segments:
                os = old_segments[key]
                ns.status = os.status
                ns.ref_audio_path = os.ref_audio_path
                ns.output_audio_path = os.output_audio_path
                ns.actual_duration = os.actual_duration
                merged_count += 1
        
        self.manifest.segments = new_segments
        self.manifest.clip_start = clip_start
        self.manifest.clip_end = clip_end
        
        # 更新 Stage 状态
        self.manifest.stages_status["parse"] = "completed"
        
        print(f"  解析到 {len(new_segments)} 个字幕段落 (恢复了 {merged_count} 个已成功的状态)")
        print(f"  处理时间范围: {clip_start:.2f}s - {clip_end:.2f}s")
        
        self.save_manifest()
    
    def _stage_clip_video(self):
        """Stage 2: 裁剪视频"""
        print("\n[Stage 2/6] 裁剪视频片段...")
        
        config.intermediate_dir.mkdir(parents=True, exist_ok=True)
        clipped_path = config.intermediate_dir / f"{self.project_name}_clip.mp4"
        
        if clipped_path.exists():
            print(f"  √ 跳过裁剪（文件已存在: {clipped_path.name}）")
            self.manifest.clipped_video = str(clipped_path)
            self.save_manifest()
            return

        clip_start = self.manifest.clip_start
        clip_duration = self.manifest.clip_end - clip_start
        
        self.audio_processor.clip_video(
            str(self.video_path),
            str(clipped_path),
            clip_start,
            clip_duration
        )
        
        self.manifest.clipped_video = str(clipped_path)
        self.manifest.stages_status["clip"] = "completed"
        self.save_manifest()
    
    def _stage_extract_audio(self):
        """Stage 3: 提取音频"""
        print("\n[Stage 3/6] 提取音频...")
        
        full_audio_path = config.intermediate_dir / f"{self.project_name}_full.wav"
        
        # 预检查分离后的文件是否已存在
        # audio-separator 产生的默认命名规则比较固定
        # 我们根据 AudioProcessor.separate_audio 的逻辑推断
        vocals_path = config.intermediate_dir / f"{self.project_name}_full_vocals.wav"
        bgm_path = config.intermediate_dir / f"{self.project_name}_full_bgm.wav"
        
        if vocals_path.exists() and bgm_path.exists():
            print(f"  √ 跳过分离（人声和背景音文件已存在）")
            self.manifest.vocal_track = str(vocals_path)
            self.manifest.bgm_track = str(bgm_path)
            self.save_manifest()
            return

        # 提取全音频
        if not full_audio_path.exists():
            self.audio_processor.extract_audio(
                self.manifest.clipped_video,
                str(full_audio_path)
            )
        
        # BGM 分离
        try:
            v_path, b_path = self.audio_processor.separate_audio(
                str(full_audio_path),
                str(config.intermediate_dir)
            )
            self.manifest.vocal_track = v_path
            self.manifest.bgm_track = b_path
            self.manifest.stages_status["extract"] = "completed"
        except Exception as e:
            print(f"  警告: 音频分离失败 ({e})，回退到使用原始音频作为人声")
            self.manifest.vocal_track = str(full_audio_path)
            self.manifest.bgm_track = None
        
        self.save_manifest()
    
    def _stage_process_segments(self):
        """Stage 4: 处理音频片段"""
        print("\n[Stage 4/6] 处理音频片段...")
        
        time_offset = self.manifest.clip_start
        skipped = 0

        for i, seg in enumerate(self.manifest.segments):
            # 物理路径检查
            expected_ref = config.segments_dir / f"ref_{seg.id:04d}.wav"
            if expected_ref.exists():
                seg.ref_audio_path = str(expected_ref)
                skipped += 1
                continue

            print(f"  处理片段 {i+1}/{len(self.manifest.segments)}: {seg.target_text[:15]}...")

            try:
                ref_audio = self.audio_processor.process_segment(
                    self.manifest.vocal_track,
                    seg,
                    str(config.segments_dir),
                    time_offset=time_offset
                )
                seg.ref_audio_path = ref_audio

            except Exception as e:
                print(f"    警告: 处理失败 - {e}")
                seg.status = "error"
                seg.error_msg = str(e)

            self.save_manifest()

        self.manifest.stages_status["process"] = "completed"
        self.save_manifest()
        processed = len(self.manifest.segments) - skipped
        if skipped > 0:
            print(f"  跳过 {skipped} 个已存在的片段，新处理 {processed} 个")
        else:
            print(f"  已处理 {len(self.manifest.segments)} 个片段")
    
    def _stage_generate_dubbing(self):
        """Stage 5: 生成配音"""
        print("\n[Stage 5/6] 生成配音...")
        
        # 统计真正需要合成的 (status == success 且文件存在)
        pending_segments = []
        for s in self.manifest.segments:
            if s.status == "success" and s.output_audio_path and Path(s.output_audio_path).exists():
                continue
            pending_segments.append(s)
            
        if not pending_segments:
            print("  所有片段已配音完成，跳过。")
            self.manifest.stages_status["generate"] = "completed"
            self.save_manifest()
            return

        print(f"  剩余 {len(pending_segments)} 个片段待合成。加载模型中...")
        self.tts_engine = TTSEngine(lazy_load=True)
        
        for i, seg in enumerate(self.manifest.segments):
            if seg.status == "success" and seg.output_audio_path and Path(seg.output_audio_path).exists():
                continue

            if seg.status == "error" or not seg.ref_audio_path:
                continue
            
            print(f"  配音片段 {i+1}/{len(self.manifest.segments)}: {seg.target_text}")
            
            try:
                seg.status = "processing"
                self.save_manifest()
                
                output_path = config.output_segments_dir / f"dub_{seg.id:04d}.wav"
                
                self.tts_engine.generate(
                    text=seg.target_text,
                    ref_audio=seg.ref_audio_path,
                    output_path=str(output_path),
                    verbose=False
                )
                
                seg.output_audio_path = str(output_path)
                seg.status = "success"
                
                # 后处理：语速调整 + 音量标准化
                try:
                    seg.actual_duration = self.audio_processor.get_duration(str(output_path))
                    target_duration = seg.duration
                    ratio = seg.actual_duration / target_duration

                    # 判断是否需要语速调整
                    speed = None
                    threshold = config.speed_no_adjust_threshold
                    if ratio < (1.0 - threshold) or ratio > (1.0 + threshold):
                        # 限制变速幅度到自然范围
                        speed = max(config.speed_min_atempo, min(config.speed_max_atempo, ratio))

                        # 检查调整后是否会超过下一句开始（防止重叠）
                        adjusted_duration = seg.actual_duration / speed
                        next_idx = i + 1
                        while next_idx < len(self.manifest.segments) and self.manifest.segments[next_idx].status == "error":
                            next_idx += 1
                        if next_idx < len(self.manifest.segments):
                            max_duration = self.manifest.segments[next_idx].start_time - seg.start_time - 0.05
                            if adjusted_duration > max_duration > 0:
                                speed = seg.actual_duration / max_duration
                                speed = min(speed, 2.0)

                    # 单次 FFmpeg 调用：变速（如需）+ 音量标准化
                    final_path = config.output_segments_dir / f"dub_{seg.id:04d}_final.wav"
                    self.audio_processor.post_process_audio(
                        str(output_path), str(final_path),
                        speed=speed,
                        target_lufs=config.target_loudness_lufs
                    )
                    seg.output_audio_path = str(final_path)
                    seg.actual_duration = self.audio_processor.get_duration(str(final_path))
                except Exception as pp_err:
                    print(f"    后处理警告: {pp_err}")
                    # 后处理失败时使用原始 TTS 输出
                    pass
                
            except Exception as e:
                print(f"    错误: {e}")
                seg.status = "error"
                seg.error_msg = str(e)
            
            self.save_manifest()
        
        # 统计成功数
        success_count = sum(1 for s in self.manifest.segments if s.status == "success")
        print(f"  配音完成: {success_count}/{len(self.manifest.segments)} 个片段")
        self.manifest.stages_status["generate"] = "completed"
        self.save_manifest()
    
    def _stage_merge_output(self):
        """Stage 6: 合并导出"""
        print("\n[Stage 6/6] 合并导出...")
        
        clip_duration = self.manifest.clip_end - self.manifest.clip_start
        time_offset = self.manifest.clip_start

        # 创建配音音轨
        dub_track = config.temp_dir / f"{self.project_name}_dub.wav"

        t0 = time.time()
        self.audio_merger.create_dubbed_track(
            self.manifest.segments,
            clip_duration,
            str(dub_track),
            time_offset=time_offset
        )
        print(f"  配音音轨创建完成 ({time.time()-t0:.1f}s)")

        self.manifest.dubbed_track = str(dub_track)

        # 生成间隙人声轨（保留笑声/哭声/歌声等无字幕的原始人声）
        dub_for_bgm = str(dub_track)
        if self.manifest.vocal_track and Path(self.manifest.vocal_track).exists():
            gap_vocal = config.intermediate_dir / f"{self.project_name}_gap_vocal.wav"
            t0 = time.time()
            try:
                self.audio_merger.create_gap_vocal_track(
                    self.manifest.vocal_track,
                    self.manifest.segments,
                    clip_duration,
                    str(gap_vocal),
                    time_offset=time_offset
                )
                # 混合配音轨 + 间隙人声轨
                combined = config.intermediate_dir / f"{self.project_name}_combined_dub.wav"
                self.audio_merger.mix_two_tracks(
                    str(dub_track), str(gap_vocal), str(combined),
                    volume_a=1.0, volume_b=1.0
                )
                dub_for_bgm = str(combined)
                print(f"  间隙人声混合完成 ({time.time()-t0:.1f}s)")
            except Exception as e:
                print(f"  警告: 间隙人声处理失败 ({e})，仅使用配音音轨")

        # 混合 BGM
        if self.manifest.bgm_track and Path(self.manifest.bgm_track).exists():
            print(f"  混合 BGM (人声 1.0x, BGM 0.6x)...")
            mixed_track = config.intermediate_dir / f"{self.project_name}_mixed.wav"

            try:
                t0 = time.time()
                self.audio_merger.mix_with_bgm(
                    dub_for_bgm,
                    str(self.manifest.bgm_track),
                    str(mixed_track),
                    dub_volume=1.0,   # 两遍 loudnorm 已精确标准化，无需额外增强
                    bgm_volume=0.8    # BGM 降至 -1.9dB，语音自然突出
                )
                print(f"  BGM 混合完成 ({time.time()-t0:.1f}s)")
                final_audio = str(mixed_track)
            except Exception as e:
                print(f"  警告: BGM 混合失败 ({e})，仅使用配音音轨")
                final_audio = dub_for_bgm
        else:
            final_audio = dub_for_bgm

        # 合并到视频
        final_video = self.output_dir / f"{self.project_name}_dubbed.mp4"

        t0 = time.time()
        self.audio_merger.merge_to_video(
            self.manifest.clipped_video,
            final_audio,
            str(final_video)
        )
        print(f"  视频合并完成 ({time.time()-t0:.1f}s)")
        
        self.manifest.final_video = str(final_video)
        self.manifest.stages_status["merge"] = "completed"
        self.save_manifest()


if __name__ == "__main__":
    # 测试
    print("Pipeline 模块加载正常")

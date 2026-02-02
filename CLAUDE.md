# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IndexDub is an AI-powered video dubbing system that uses IndexTTS2 (Bilibili's text-to-speech model) to automatically generate voice dubbing for videos based on bilingual subtitles. The system processes video in stages with checkpoint/resume support.

## Essential Commands

### Running the System

**推荐方式: 使用 run.bat 脚本**

```bash
# 自动处理虚拟环境和离线模式（推荐）
run.bat --demo
run.bat --demo --force
run.bat --full
```

**优点**:
- 自动使用虚拟环境 Python
- 启用 HuggingFace 离线模式（避免网络连接问题）
- 无需手动激活虚拟环境

**原始方式: 手动管理环境**

```bash
# Activate virtual environment first (Windows CMD)
.venv\Scripts\activate

# Or directly use venv Python
.venv\Scripts\python.exe main.py [args]

# Or use uv
uv run python main.py [args]
```

**Common workflows**:
```bash
# Quick test (5 segments, 60-180s range)
run.bat --demo

# Custom time range
run.bat --start-time 600 --end-time 750 --max-segments 50

# Full video processing
run.bat --full

# Force restart (cleans all intermediate files)
run.bat --demo --force

# Test preprocessing only (no TTS loading)
run.bat test_preprocessing.py
```

### Dependency Management

```bash
# Install dependencies (requires Python 3.10+)
pip install -r requirements.txt

# Verify FFmpeg
ffmpeg -version

# Check if audio-separator has GPU support
uv run --with "audio-separator[gpu,onnxruntime-gpu]" audio-separator --env_info
```

## Architecture

### Pipeline Stages

The system processes videos through 6 sequential stages managed by [pipeline.py](src/pipeline.py):

1. **Stage 1: Parse Subtitles** ([subtitle_parser.py](src/subtitle_parser.py))
   - Parses SRT/ASS files
   - Extracts bilingual text (source + target)
   - Filters by time range and max segments

2. **Stage 2: Clip Video** ([audio_processor.py](src/audio_processor.py))
   - Clips video to target time range using FFmpeg
   - Adds padding to avoid boundary issues
   - Output: `temp/intermediate/{project}_clip.mp4`

3. **Stage 3: Extract and Separate Audio** ([audio_processor.py](src/audio_processor.py))
   - Extracts full audio track
   - Separates vocals from BGM using audio-separator with UVR-MDX-NET model
   - GPU acceleration via audio-separator[gpu,onnxruntime-gpu]
   - Outputs: `*_vocals.wav` (human voice) and `*_bgm.wav` (background music)

4. **Stage 4: Process Segments** ([audio_processor.py](src/audio_processor.py))
   - For each subtitle segment:
     - Clips exact vocal segment
     - Applies noise reduction (FFmpeg afftdn filter)
     - Adds padding for TTS reference
   - Outputs: `temp/segments/seg_*.wav` and `ref_*.wav`

5. **Stage 5: Generate Dubbing** ([tts_engine.py](src/tts_engine.py))
   - Loads IndexTTS2 model (~5GB, first run takes several minutes)
   - For each segment: generates dubbed audio using target text + reference audio
   - Adjusts speed to match original duration
   - Output: `temp/output/dub_*.wav`

6. **Stage 6: Merge and Export** ([audio_merger.py](src/audio_merger.py))
   - Merges all dubbed segments into single track
   - Mixes with original BGM
   - Merges final audio with video
   - Output: `output/{project}_dubbed.mp4`

### Checkpoint/Resume System

**Manifest file**: `temp/{project}_manifest.json`

- Tracks completion status for each stage and segment
- Allows interruption and resumption without reprocessing
- Double verification: checks both manifest status AND file existence
- `--force` flag bypasses checkpoint system and cleans all intermediate files

### Key Components

- **[config.py](src/config.py)**: Global configuration (paths, audio parameters, demo settings)
- **[tts_engine.py](src/tts_engine.py)**: Wrapper around IndexTTS2 model
- **IndexTTS2 integration**: Located in `index-tts/` subdirectory with separate pyproject.toml

### Directory Structure

```
temp/
├── {project}_manifest.json       # Checkpoint state
├── intermediate/
│   ├── {project}_clip.mp4        # Stage 2
│   ├── {project}_full.wav
│   ├── {project}_full_vocals.wav # Stage 3
│   └── {project}_full_bgm.wav    # Stage 3
├── segments/
│   ├── seg_*.wav                 # Stage 4: raw clips
│   └── ref_*.wav                 # Stage 4: processed for TTS
└── output/
    ├── dub_*.wav                 # Stage 5: generated dubbing
    └── dub_*_adj.wav             # Stage 5: speed-adjusted

output/
└── {project}_dubbed.mp4          # Final result (never deleted)
```

## Important Technical Details

### Subprocess Encoding on Windows

**All subprocess.run calls MUST include**:
```python
result = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    encoding='utf-8',
    errors='replace'
)
```

Without this, FFmpeg UTF-8 output causes `UnicodeDecodeError` on Windows (default GBK encoding).

### audio-separator GPU Usage

- GPU is enabled via package variant: `audio-separator[gpu,onnxruntime-gpu]`
- **Do NOT use** `--device cuda` CLI parameter (not supported)
- Automatically uses GPU when CUDA is available

### IndexTTS2 Model

- Located: `index-tts/checkpoints/`
- Config: `index-tts/checkpoints/config.yaml`
- Requires ~8-10GB GPU memory
- Uses FP16 for memory efficiency (`config.use_fp16 = True`)
- CUDA kernels disabled on Windows (`config.use_cuda_kernel = False`)

### Virtual Environment Requirement

**Users MUST activate `.venv` before running**. The virtual environment contains:
- librosa, torch, torchaudio (PyTorch with CUDA 12.8)
- All IndexTTS2 dependencies
- audio-separator with GPU support

If users report "No module named 'librosa'" or similar:
- Root cause: Running with system Python instead of venv Python
- Solution: Activate venv first (see commands above)

### --force Parameter Behavior

When `--force` is used:
1. Calls `_clean_intermediate_files()` in [pipeline.py:158-220](src/pipeline.py)
2. Deletes manifest and all temp files matching `{project_name}_*`
3. Preserves only final output video in `output/`
4. Ensures complete restart from Stage 1

## Common Issues

### Encoding Errors
- Symptom: `UnicodeDecodeError: 'gbk' codec can't decode`
- Fix: Ensure all subprocess calls include `encoding='utf-8', errors='replace'`

### Module Import Errors
- Symptom: `No module named 'librosa'` or similar
- Fix: Verify virtual environment is activated before running

### GPU Not Used
- Verify: `nvidia-smi` shows GPU activity during Stage 3 (audio separation)
- Check: `uv run --with "audio-separator[gpu,onnxruntime-gpu]" audio-separator --env_info` shows CUDA support

### Stage Skipping Issues
- If stages incorrectly skip: Delete `temp/{project}_manifest.json` or use `--force`
- `--force` is preferred for complete clean restart

## IndexTTS2 Configuration

Key parameters in [config.py](src/config.py):
- `sample_rate: 22050` - IndexTTS2 output sample rate
- `padding_ms: 100` - Silence padding for audio clips
- `denoise_strength: 10` - FFmpeg noise reduction (0-100)
- `demo_max_segments: 5` - Max segments in demo mode
- `demo_start_time: 60.0`, `demo_end_time: 120.0` - Demo time range

## Development Notes

- Python 3.10+ required (IndexTTS2 constraint)
- FFmpeg must be in system PATH
- CUDA GPU with 12GB+ VRAM recommended
- Windows: UTF-8 encoding forced in main.py and test scripts

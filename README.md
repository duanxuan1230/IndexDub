# IndexDub - AI 视频自动配音系统

基于 [IndexTTS 2.0](https://github.com/index-tts/index-tts)（Bilibili 开源 TTS 模型）的视频自动化配音工具。输入视频 + 双语字幕，自动生成中文配音并合成到视频中。

## 特性

- 自动解析双语字幕（SRT / ASS 格式）
- AI 声音克隆配音（基于原声参考音频）
- 人声 / BGM 智能分离，保留背景音乐
- 语速自动调整，匹配原始时间轴
- 两遍 EBU R128 响度标准化，音量一致
- 非配音区间原声保留（笑声、哭声、歌声等）
- 断点续传，中断后可继续处理
- 阿拉伯数字自动转中文读法

## 系统要求

| 项目 | 要求 | 说明 |
|------|------|------|
| **操作系统** | Windows 10/11 | 目前仅测试 Windows |
| **GPU** | NVIDIA 显卡，12GB+ 显存 | **必须**，IndexTTS2 不支持 CPU 推理 |
| **CUDA** | CUDA 12.x | 随 NVIDIA 驱动安装 |
| **Python** | 3.10+ | IndexTTS2 要求 |
| **FFmpeg** | 任意版本 | 须加入系统 PATH |
| **磁盘空间** | 约 10GB+ | 模型 ~5GB + 运行时临时文件 |
| **内存** | 16GB+ 推荐 | 音频分离阶段内存占用较大 |

> **重要**: 本项目依赖 NVIDIA CUDA 显卡进行 TTS 推理，无 NVIDIA 显卡将**无法运行**。

## 从零开始安装

### Step 1: 安装前置工具

#### 1.1 安装 Python 3.10+

从 [python.org](https://www.python.org/downloads/) 下载安装，**安装时勾选 "Add Python to PATH"**。

验证：
```bash
python --version   # 应显示 3.10.x 或更高
```

#### 1.2 安装 FFmpeg

1. 从 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 下载 `ffmpeg-release-essentials.zip`
2. 解压到任意目录（如 `C:\ffmpeg`）
3. 将 `C:\ffmpeg\bin` 添加到系统环境变量 PATH

验证：
```bash
ffmpeg -version    # 应显示版本信息
```

#### 1.3 安装 uv（Python 包管理器）

```bash
pip install uv
```

> uv 比 pip 快 10-100 倍，且能正确处理 PyTorch CUDA 版本。

#### 1.4 确认 NVIDIA 显卡和驱动

```bash
nvidia-smi         # 应显示显卡信息和 CUDA 版本
```

如果此命令不可用，请先安装 [NVIDIA 驱动](https://www.nvidia.com/download/index.aspx)。

### Step 2: 克隆项目

```bash
git clone https://github.com/你的用户名/IndexDub.git
cd IndexDub
```

### Step 3: 下载模型权重

IndexTTS2 源码已包含在仓库的 `index-tts/` 目录中，但模型权重文件（~5GB）需要手动下载到 `index-tts/checkpoints/` 目录。

从 HuggingFace 下载：[IndexTeam/IndexTTS2](https://huggingface.co/IndexTeam/IndexTTS2)

下载后目录结构应为：
```
index-tts/checkpoints/
├── config.yaml
├── gpt.pth          (~3.3 GB)
├── s2mel.pth         (~1.2 GB)
├── bpe.model
├── feat1.pt
├── feat2.pt
├── pinyin.vocab
└── wav2vec2bert_stats.pt
```

### Step 4: 安装 Python 依赖

```bash
setup_env.bat
```

这会自动创建虚拟环境并安装所有依赖（包括 CUDA 版 PyTorch），需要几分钟。

#### 验证安装

```bash
.venv\Scripts\python.exe -c "import torch; print(f'PyTorch {torch.__version__}, CUDA: {torch.cuda.is_available()}')"
```

应输出 `PyTorch 2.8.0, CUDA: True`。如果 CUDA 显示 False，说明 PyTorch CUDA 版本未正确安装。

### Step 5: 准备素材

将视频文件和对应的双语字幕放入 `example/` 目录，然后修改 `main.py` 中的默认路径，或通过命令行参数指定。

## 快速开始

### Demo 模式（推荐先试）

```bash
run.bat --demo
```

默认处理 60s-180s 范围内的 5 个字幕片段。首次运行会加载 TTS 模型（约 5 分钟）。

### 自定义时间范围

```bash
# 处理 600s-750s 之间的 50 个片段
run.bat --start-time 600 --end-time 750 --max-segments 50
```

### 处理完整视频

```bash
run.bat --full
```

### 强制从头开始

```bash
run.bat --demo --force
```

`--force` 会清除所有中间文件和状态，完全重新运行。

### 输出

配音完成后，输出文件在 `output/` 目录：
```
output/{项目名}_dubbed.mp4
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--video`, `-v` | 视频文件路径 | example/ 下的默认视频 |
| `--subtitle`, `-s` | 字幕文件路径 | example/ 下的默认字幕 |
| `--output`, `-o` | 输出目录 | output/ |
| `--demo` | Demo 模式（默认） | True |
| `--full` | 处理完整视频 | False |
| `--max-segments` | 最大处理句数 | 5 |
| `--start-time` | 开始时间（秒） | 60 |
| `--end-time` | 结束时间（秒） | 180 |
| `--force` | 强制重新运行（清除所有中间文件） | False |

## 处理流程

```
视频 + 字幕
    │
    ├─ Stage 1: 解析字幕 ─────── 提取双语文本，过滤时间范围
    ├─ Stage 2: 裁剪视频 ─────── FFmpeg 按时间范围裁剪
    ├─ Stage 3: 分离音频 ─────── UVR-MDX-NET 人声/BGM 分离（耗时最长）
    ├─ Stage 4: 处理片段 ─────── 按字幕切分音频，降噪，生成参考音频
    ├─ Stage 5: 生成配音 ─────── IndexTTS2 克隆配音 + 语速调整 + 音量标准化
    └─ Stage 6: 合并导出 ─────── 配音 + 间隙原声 + BGM → 最终视频
```

每个阶段完成后自动保存状态，中断后重新运行会跳过已完成的阶段。

## 项目结构

```
IndexDub/
├── index-tts/              # IndexTTS2 源码（已包含）
│   └── checkpoints/        # 模型权重（需单独下载，已 gitignore）
├── src/                    # 源代码
│   ├── config.py           # 全局配置
│   ├── pipeline.py         # 主流程控制
│   ├── subtitle_parser.py  # 字幕解析（SRT/ASS）
│   ├── audio_processor.py  # 音频处理（裁剪/降噪/标准化）
│   ├── tts_engine.py       # TTS 引擎封装
│   └── audio_merger.py     # 音频混合与视频合成
├── example/                # 素材目录（视频 + 字幕）
├── temp/                   # 运行时临时文件
├── output/                 # 最终输出
├── main.py                 # 程序入口
├── run.bat                 # 便捷运行脚本
├── setup_env.bat           # 环境安装脚本
└── requirements.txt        # Python 依赖
```

## 常见问题

### "No module named 'librosa'" 或类似导入错误

**原因**: 使用了系统 Python 而非虚拟环境。

**解决**: 使用 `run.bat` 运行，或先激活虚拟环境：
```bash
.venv\Scripts\activate
python main.py --demo
```

### "CUDA is not available" / GPU 未被使用

**检查步骤**:
1. `nvidia-smi` 确认驱动正常
2. `.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"` 确认 PyTorch CUDA
3. 如果返回 False，重新运行 `setup_env.bat` 安装 CUDA 版 PyTorch

### FFmpeg 相关错误

**原因**: FFmpeg 未安装或未加入 PATH。

**验证**: `ffmpeg -version`，如果命令不可用，请安装 FFmpeg 并添加到系统 PATH。

### UnicodeDecodeError（GBK 编码错误）

**原因**: Windows 默认使用 GBK 编码。

**解决**: 使用 `run.bat` 运行（已内置 UTF-8 处理），不要直接 `python main.py`。

### 音频分离阶段卡住（Stage 3 长时间无输出）

**说明**: 音频分离是最耗时的阶段（10-30 分钟），取决于视频长度。程序会实时打印分离进度，请耐心等待。

### 如何更换配音的视频/字幕？

通过命令行参数指定：
```bash
run.bat --video "path/to/video.mp4" --subtitle "path/to/subtitle.srt" --demo
```

或修改 `main.py` 中的默认路径。

## 致谢

- [IndexTTS2](https://github.com/index-tts/index-tts) - Bilibili 开源 TTS 模型
- [audio-separator](https://github.com/nomadkaraoke/python-audio-separator) - 人声/BGM 分离
- [FFmpeg](https://ffmpeg.org/) - 音视频处理

## 许可证

本项目仅供学习研究使用。IndexTTS2 模型受 [Bilibili IndexTTS License](https://github.com/index-tts/index-tts/blob/main/LICENSE) 约束。

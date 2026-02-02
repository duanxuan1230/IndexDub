"""
TTS 引擎模块
封装 IndexTTS2 进行配音生成
"""
import sys
import os
import time
from pathlib import Path
from typing import Optional

from .config import config


class TTSEngine:
    """IndexTTS2 TTS 引擎封装"""
    
    def __init__(self, lazy_load: bool = True):
        """
        初始化 TTS 引擎
        
        Args:
            lazy_load: 是否延迟加载模型（首次调用 generate 时加载）
        """
        self.tts = None
        self.model_loaded = False
        
        # 添加 index-tts 到路径
        indextts_path = str(config.indextts_dir)
        if indextts_path not in sys.path:
            sys.path.insert(0, indextts_path)
        
        if not lazy_load:
            self._load_model()
    
    def _load_model(self):
        """加载 IndexTTS2 模型"""
        if self.model_loaded:
            return
        
        print(">> 正在加载 IndexTTS2 模型...")
        print(f"   配置文件: {config.indextts_config}")
        print(f"   模型目录: {config.indextts_checkpoint_dir}")

        # 切换工作目录到 index-tts（某些模型依赖相对路径）
        original_cwd = os.getcwd()
        os.chdir(str(config.indextts_dir))

        t0 = time.time()
        try:
            from indextts.infer_v2 import IndexTTS2

            self.tts = IndexTTS2(
                cfg_path=str(config.indextts_config),
                model_dir=str(config.indextts_checkpoint_dir),
                use_fp16=config.use_fp16,
                use_cuda_kernel=config.use_cuda_kernel,
                use_deepspeed=False
            )

            self.model_loaded = True
            elapsed = time.time() - t0
            print(f">> IndexTTS2 模型加载完成 ({elapsed:.1f}s)")
            
        finally:
            os.chdir(original_cwd)
    
    def generate(self, text: str, ref_audio: str, output_path: str,
                 verbose: bool = True) -> str:
        """
        生成配音音频
        
        Args:
            text: 要合成的中文文本
            ref_audio: 参考音频路径（用于音色克隆）
            output_path: 输出音频路径
            verbose: 是否显示详细信息
            
        Returns:
            输出音频路径
        """
        if not self.model_loaded:
            self._load_model()
        
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        if verbose:
            print(f">> 生成配音: {text[:30]}...")
        
        # 调用 IndexTTS2 推理
        self.tts.infer(
            spk_audio_prompt=ref_audio,
            text=text,
            output_path=str(output),
            verbose=verbose
        )
        
        if verbose:
            print(f">> 配音已保存: {output}")
        
        return str(output)
    
    def unload(self):
        """卸载模型以释放显存"""
        if self.tts is not None:
            del self.tts
            self.tts = None
            self.model_loaded = False
            
            # 尝试清理 GPU 显存
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    print(">> GPU 显存已清理")
            except:
                pass
            
            print(">> IndexTTS2 模型已卸载")


if __name__ == "__main__":
    # 测试（需要 GPU）
    print("TTSEngine 模块加载正常")
    print("注意：实际测试需要加载模型，请通过 main.py 运行完整流程")

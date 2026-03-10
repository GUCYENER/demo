"""
VYRA L1 Support API - RAG Embedding Manager
=============================================
ONNX/PyTorch tabanlı embedding model yönetimi.
Lazy loading, cache desteği ve batch embedding.

🚀 v2.28.0: ONNX backend ile hızlı model yükleme (fallback: PyTorch)
"""

from __future__ import annotations

from typing import List

from app.core.config import settings
from app.services.logging_service import log_system_event, log_error


class EmbeddingManager:
    """
    Embedding model yöneticisi.
    
    - ONNX öncelikli, PyTorch fallback
    - Lazy loading (ilk kullanımda yüklenir)
    - Cache destekli embedding üretimi
    """
    
    def __init__(self):
        self._embedding_model = None
        self._onnx_session = None
        self._onnx_tokenizer = None
        self._backend = None  # "onnx" veya "pytorch"
        self._embedding_dim = 384  # MiniLM default
    
    @property
    def backend(self) -> str | None:
        return self._backend
    
    @backend.setter
    def backend(self, value):
        self._backend = value
    
    def _try_load_onnx(self) -> bool:
        """
        🚀 v2.28.0: ONNX modelini yüklemeyi dener.
        
        Returns:
            True: ONNX başarıyla yüklendi
            False: ONNX yüklenemedi, fallback gerekli
        """
        import os
        import time
        
        onnx_path = os.path.join(os.path.dirname(__file__), "../../../models/embedding/model.onnx")
        onnx_path = os.path.abspath(onnx_path)
        
        if not os.path.exists(onnx_path):
            log_system_event("DEBUG", f"ONNX model bulunamadı: {onnx_path}", "rag")
            return False
        
        try:
            t0 = time.time()
            import onnxruntime as ort
            # 🚀 transformers yerine doğrudan tokenizers kullan (115s → <1s)
            from tokenizers import Tokenizer
            
            # ONNX Session oluştur
            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_options.intra_op_num_threads = 4
            
            self._onnx_session = ort.InferenceSession(
                onnx_path,
                sess_options,
                providers=['CPUExecutionProvider']
            )
            
            # 🚀 Tokenizer yükle (tokenizers kütüphanesi ile - çok hızlı!)
            tokenizer_path = os.path.dirname(onnx_path)
            tokenizer_json = os.path.join(tokenizer_path, "tokenizer.json")
            self._onnx_tokenizer = Tokenizer.from_file(tokenizer_json)
            
            self._backend = "onnx"
            load_time = time.time() - t0
            log_system_event("INFO", f"🚀 ONNX embedding model yüklendi ({load_time:.2f}s)", "rag")
            return True
            
        except Exception as e:
            log_system_event("WARNING", f"ONNX yüklenemedi, PyTorch fallback: {e}", "rag")
            self._onnx_session = None
            self._onnx_tokenizer = None
            return False
    
    def _load_pytorch_model(self):
        """PyTorch tabanlı sentence-transformers modelini yükler (fallback)"""
        import os
        import time
        
        t0 = time.time()
        
        # ⚡ HuggingFace OFFLINE mode (Portable: proje içi cache)
        from app.core.config import BASE_DIR
        hf_cache_dir = str(BASE_DIR / 'models' / 'hf_cache')
        if os.path.exists(hf_cache_dir):
            os.environ['HF_HOME'] = hf_cache_dir
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        os.environ['HF_HUB_DISABLE_SSL_VERIFY'] = '1'
        os.environ['REQUESTS_CA_BUNDLE'] = ''
        os.environ['CURL_CA_BUNDLE'] = ''
        os.environ['ACCELERATE_TORCH_DEVICE'] = 'cpu'
        
        try:
            from sentence_transformers import SentenceTransformer
            model_name = getattr(settings, 'EMBEDDING_MODEL', 'paraphrase-multilingual-MiniLM-L12-v2')
            
            self._embedding_model = SentenceTransformer(
                model_name, 
                local_files_only=True,
                device='cpu'
            )
            self._backend = "pytorch"
            load_time = time.time() - t0
            log_system_event("INFO", f"⚠️ PyTorch embedding model yüklendi (offline, {load_time:.2f}s)", "rag")
            
        except Exception as e:
            log_system_event("WARNING", f"Offline model yüklenemedi, online deneniyor: {str(e)}", "rag")
            try:
                from sentence_transformers import SentenceTransformer
                model_name = getattr(settings, 'EMBEDDING_MODEL', 'paraphrase-multilingual-MiniLM-L12-v2')
                self._embedding_model = SentenceTransformer(model_name, device='cpu')
                self._backend = "pytorch"
                log_system_event("INFO", f"PyTorch embedding model yüklendi (online)", "rag")
            except ImportError:
                log_error("sentence-transformers yüklü değil", "rag")
                raise ImportError("sentence-transformers yüklü değil. 'pip install sentence-transformers' çalıştırın.")
    
    @property
    def embedding_model(self):
        """Embedding modelini lazy load eder (ONNX öncelikli, PyTorch fallback)"""
        if self._backend is None:
            # 1. ONNX dene (hızlı: ~10s)
            if self._try_load_onnx():
                return self._onnx_session  # ONNX session döndür
            
            # 2. Fallback: PyTorch (yavaş: ~200s ama güvenilir)
            self._load_pytorch_model()
        
        return self._embedding_model if self._backend == "pytorch" else self._onnx_session
    
    def _onnx_encode(self, text: str) -> List[float]:
        """ONNX ile embedding üretir (tokenizers kütüphanesi ile)"""
        import numpy as np
        
        # Tokenize (tokenizers kütüphanesi API'si)
        encoding = self._onnx_tokenizer.encode(text)
        
        # Input arrays oluştur (batch size = 1)
        input_ids = np.array([encoding.ids], dtype=np.int64)
        attention_mask = np.array([encoding.attention_mask], dtype=np.int64)
        
        # Input dict oluştur
        input_dict = {
            "input_ids": input_ids,
            "attention_mask": attention_mask
        }
        
        # Token type ids varsa ekle (BERT modelleri için)
        if encoding.type_ids:
            input_dict["token_type_ids"] = np.array([encoding.type_ids], dtype=np.int64)
        
        # Inference
        outputs = self._onnx_session.run(None, input_dict)
        
        # Mean pooling (attention mask ile)
        token_embeddings = outputs[0]  # (batch_size, seq_len, hidden_dim)
        
        # Mask'ı genişlet
        mask_expanded = np.expand_dims(attention_mask, axis=-1)
        mask_expanded = np.broadcast_to(mask_expanded, token_embeddings.shape)
        
        # Weighted mean
        sum_embeddings = np.sum(token_embeddings * mask_expanded, axis=1)
        sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
        embedding = sum_embeddings / sum_mask
        
        return embedding[0].tolist()
    
    def get_embedding(self, text: str) -> List[float]:
        """Metin için embedding vektörü üretir (cache destekli, ONNX/PyTorch)"""
        from app.core.cache import cache_service
        import hashlib
        
        # Cache key oluştur
        cache_key = f"emb:{hashlib.md5(text.encode('utf-8')).hexdigest()}"
        
        # Cache'den kontrol et
        cached = cache_service.embedding.get(cache_key)
        if cached is not None:
            return cached
        
        # Model henüz yüklenmemişse yükle
        _ = self.embedding_model
        
        # Hesapla ve cache'e kaydet
        try:
            # 🚀 ONNX backend
            if self._backend == "onnx":
                embedding_list = self._onnx_encode(text)
            else:
                # PyTorch backend
                embedding = self._embedding_model.encode(text)
                embedding_list = embedding.tolist()
            
            cache_service.embedding.set(cache_key, embedding_list, ttl=0)  # Sonsuz TTL
            return embedding_list
            
        except Exception as e:
            # "meta tensor" hatası durumunda modeli yeniden yükle (PyTorch only)
            if "meta tensor" in str(e) and self._backend == "pytorch":
                log_system_event("WARNING", f"Embedding model hatası, yeniden yükleniyor: {e}", "rag")
                self._embedding_model = None
                self._backend = None
                _ = self.embedding_model  # Yeniden yükle
                return self.get_embedding(text)  # Tekrar dene
            raise  # Diğer hataları yukarı ilet
    
    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Birden fazla metin için embedding üretir (batch, ONNX/PyTorch)"""
        # Model henüz yüklenmemişse yükle
        _ = self.embedding_model
        
        if self._backend == "onnx":
            # ONNX ile batch embedding
            return [self._onnx_encode(text) for text in texts]
        else:
            # PyTorch ile batch embedding
            embeddings = self._embedding_model.encode(texts)
            return [emb.tolist() for emb in embeddings]

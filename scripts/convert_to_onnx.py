"""
VYRA - PyTorch Model → ONNX Dönüştürücü
========================================
Bu script, models/hf_model/ dizinindeki PyTorch (SafeTensors) modelini
ONNX formatına dönüştürür ve models/embedding/ dizinine kaydeder.

Kullanım:
    python scripts/convert_to_onnx.py

Çıktı:
    models/embedding/model.onnx
    models/embedding/tokenizer.json

v2.60.2: ONNX dönüştürme scripti eklendi.
"""

import os
import sys
import time
import shutil
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("onnx_converter")

# Proje kök dizini
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

HF_MODEL_DIR = os.path.join(PROJECT_ROOT, "models", "hf_model")
ONNX_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "models", "embedding")
ONNX_MODEL_PATH = os.path.join(ONNX_OUTPUT_DIR, "model.onnx")
TOKENIZER_SRC = os.path.join(HF_MODEL_DIR, "tokenizer.json")
TOKENIZER_DST = os.path.join(ONNX_OUTPUT_DIR, "tokenizer.json")


def check_prerequisites():
    """Gerekli dosya ve kütüphaneleri kontrol eder."""
    # Kaynak model kontrolü
    config_file = os.path.join(HF_MODEL_DIR, "config.json")
    if not os.path.isfile(config_file):
        logger.error(f"Kaynak model bulunamadı: {config_file}")
        logger.error("Önce models/hf_model/ dizinine model dosyalarını kopyalayın.")
        sys.exit(1)

    safetensors_file = os.path.join(HF_MODEL_DIR, "model.safetensors")
    if not os.path.isfile(safetensors_file):
        logger.error(f"Model dosyası bulunamadı: {safetensors_file}")
        sys.exit(1)

    if not os.path.isfile(TOKENIZER_SRC):
        logger.error(f"Tokenizer bulunamadı: {TOKENIZER_SRC}")
        sys.exit(1)

    # Kütüphane kontrolleri
    try:
        import torch  # noqa: F401
        logger.info(f"PyTorch: {torch.__version__}")
    except ImportError:
        logger.error("PyTorch yüklü değil. 'pip install torch' çalıştırın.")
        sys.exit(1)

    try:
        import onnx  # noqa: F401
        logger.info(f"ONNX: {onnx.__version__}")
    except ImportError:
        logger.error("ONNX yüklü değil. 'pip install onnx' çalıştırın.")
        sys.exit(1)

    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
        logger.info("sentence-transformers: OK")
    except ImportError:
        logger.error("sentence-transformers yüklü değil.")
        sys.exit(1)

    logger.info("Tüm gereksinimler mevcut ✅")


def convert_to_onnx():
    """PyTorch modelini ONNX formatına dönüştürür."""
    import torch
    from sentence_transformers import SentenceTransformer

    # Çıktı dizini oluştur
    os.makedirs(ONNX_OUTPUT_DIR, exist_ok=True)

    # 1. Modeli yükle
    logger.info(f"Model yükleniyor: {HF_MODEL_DIR}")
    t0 = time.time()

    # Offline mod
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'

    model = SentenceTransformer(HF_MODEL_DIR, device='cpu')
    load_time = time.time() - t0
    logger.info(f"Model yüklendi ({load_time:.1f}s)")

    # 2. Transformer modülünü al
    transformer_module = model[0]  # İlk modül = Transformer
    auto_model = transformer_module.auto_model

    # 3. Dummy input oluştur
    logger.info("ONNX dönüştürme başlıyor...")
    t0 = time.time()

    tokenizer = transformer_module.tokenizer
    dummy_text = "Bu bir test cümlesidir."
    encoded = tokenizer(dummy_text, return_tensors="pt", padding=True, truncation=True, max_length=128)

    input_ids = encoded["input_ids"]
    attention_mask = encoded["attention_mask"]

    # Token type ids (BERT modelleri için)
    has_token_type_ids = "token_type_ids" in encoded
    token_type_ids = encoded.get("token_type_ids")

    # 4. ONNX export
    dynamic_axes = {
        "input_ids": {0: "batch_size", 1: "sequence"},
        "attention_mask": {0: "batch_size", 1: "sequence"},
        "output": {0: "batch_size", 1: "sequence"},
    }

    input_names = ["input_ids", "attention_mask"]
    input_tuple = (input_ids, attention_mask)

    if has_token_type_ids:
        input_names.append("token_type_ids")
        input_tuple = (input_ids, attention_mask, token_type_ids)
        dynamic_axes["token_type_ids"] = {0: "batch_size", 1: "sequence"}

    torch.onnx.export(
        auto_model,
        input_tuple,
        ONNX_MODEL_PATH,
        input_names=input_names,
        output_names=["output"],
        dynamic_axes=dynamic_axes,
        opset_version=14,
        do_constant_folding=True,
    )

    convert_time = time.time() - t0
    onnx_size_mb = os.path.getsize(ONNX_MODEL_PATH) / (1024 * 1024)
    logger.info(f"ONNX model oluşturuldu ({convert_time:.1f}s, {onnx_size_mb:.1f} MB)")
    logger.info(f"  → {ONNX_MODEL_PATH}")

    # 5. Tokenizer'ı kopyala
    shutil.copy2(TOKENIZER_SRC, TOKENIZER_DST)
    logger.info(f"Tokenizer kopyalandı → {TOKENIZER_DST}")

    # 6. Doğrulama
    logger.info("ONNX model doğrulanıyor...")
    import onnx
    onnx_model = onnx.load(ONNX_MODEL_PATH)
    onnx.checker.check_model(onnx_model)
    logger.info("ONNX model geçerli ✅")

    # 7. Basit inference testi
    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
        import numpy as np

        logger.info("ONNX inference testi yapılıyor...")
        session = ort.InferenceSession(ONNX_MODEL_PATH, providers=['CPUExecutionProvider'])
        fast_tokenizer = Tokenizer.from_file(TOKENIZER_DST)

        encoding = fast_tokenizer.encode("Test cümlesi")
        inp = {
            "input_ids": np.array([encoding.ids], dtype=np.int64),
            "attention_mask": np.array([encoding.attention_mask], dtype=np.int64),
        }
        if has_token_type_ids and encoding.type_ids:
            inp["token_type_ids"] = np.array([encoding.type_ids], dtype=np.int64)

        outputs = session.run(None, inp)
        embedding_dim = outputs[0].shape[-1]
        logger.info(f"ONNX inference başarılı ✅ (embedding dim: {embedding_dim})")

    except ImportError:
        logger.warning("onnxruntime veya tokenizers yüklü değil, inference testi atlandı.")
    except Exception as e:
        logger.warning(f"Inference testi başarısız (model yine de kullanılabilir): {e}")

    logger.info("")
    logger.info("=" * 60)
    logger.info("  DÖNÜŞTÜRME TAMAMLANDI!")
    logger.info(f"  ONNX model:  {ONNX_MODEL_PATH}")
    logger.info(f"  Tokenizer:   {TOKENIZER_DST}")
    logger.info(f"  Boyut:       {onnx_size_mb:.1f} MB")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Bu iki dosyayı canlı sunucuya kopyalayın:")
    logger.info(f"  models/embedding/model.onnx")
    logger.info(f"  models/embedding/tokenizer.json")


if __name__ == "__main__":
    logger.info("VYRA ONNX Model Dönüştürücü")
    logger.info(f"Proje kökü: {PROJECT_ROOT}")
    logger.info(f"Kaynak:     {HF_MODEL_DIR}")
    logger.info(f"Hedef:      {ONNX_OUTPUT_DIR}")
    logger.info("")

    check_prerequisites()
    convert_to_onnx()

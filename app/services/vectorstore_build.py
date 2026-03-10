"""
Vectorstore Build Service
Yüklenen dosyalardan vektör veritabanını oluşturur
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from app.core.config import settings
from app.services.logging_service import log_error, log_system_event, log_warning
from app.services.document_processors import get_processor, SUPPORTED_EXTENSIONS
from app.services.document_processors.base import ProcessedDocument
from app.services.rag_service import get_rag_service


@dataclass
class BuildResult:
    """Build sonucu"""
    success: bool
    processed_files: int
    total_chunks: int
    failed_files: List[str]
    errors: List[str]


def generate_chunk_id(source_file: str, chunk_index: int) -> str:
    """Chunk için benzersiz ID oluşturur"""
    content = f"{source_file}_{chunk_index}"
    return hashlib.md5(content.encode()).hexdigest()


def process_single_file(file_path: Path) -> Optional[ProcessedDocument]:
    """
    Tek bir dosyayı işler ve ProcessedDocument döndürür.
    
    Args:
        file_path: İşlenecek dosya yolu
        
    Returns:
        ProcessedDocument veya None (hata durumunda)
    """
    try:
        ext = file_path.suffix.lower()
        
        if ext not in SUPPORTED_EXTENSIONS:
            log_warning(f"Desteklenmeyen dosya formatı: {ext}", "vectorstore")
            return None
        
        processor = get_processor(ext)
        doc = processor.process(file_path)
        
        log_system_event(
            "INFO",
            f"Dosya işlendi: {file_path.name} - {doc.total_chunks} chunk",
            "vectorstore"
        )
        
        return doc
        
    except Exception as e:
        log_error(f"Dosya işleme hatası: {file_path.name} - {str(e)}", "vectorstore", error_detail=str(e))
        return None


def rebuild_vectorstore_from_uploaded_files(
    uploads_dir: str | Path | None = None,
    persist_dir: str | Path | None = None,
    reset_existing: bool = True
) -> BuildResult:
    """
    uploads_dir altındaki tüm desteklenen dosyalardan vektör veritabanını yeniden kurar.
    
    Args:
        uploads_dir: Yüklenen dosyaların bulunduğu klasör
        persist_dir: Vektör veritabanının kaydedileceği klasör
        reset_existing: True ise mevcut veritabanını sıfırlar
        
    Returns:
        BuildResult objesi
    """
    udir = Path(uploads_dir or settings.uploads_dir)
    
    # Klasör yoksa oluştur
    udir.mkdir(parents=True, exist_ok=True)
    
    # Desteklenen dosyaları bul
    files_to_process: List[Path] = []
    for ext in SUPPORTED_EXTENSIONS:
        files_to_process.extend(udir.glob(f"*{ext}"))
    
    if not files_to_process:
        log_warning("İşlenecek dosya bulunamadı", "vectorstore")
        return BuildResult(
            success=True,
            processed_files=0,
            total_chunks=0,
            failed_files=[],
            errors=[]
        )
    
    log_system_event("INFO", f"{len(files_to_process)} dosya işlenecek", "vectorstore")
    
    # RAG servisini al
    rag_service = get_rag_service()
    
    # Mevcut veritabanını sıfırla
    if reset_existing:
        try:
            rag_service.reset()
        except Exception as e:
            log_warning(f"Reset sırasında hata: {str(e)}", "vectorstore")
    
    # Dosyaları işle
    processed_count = 0
    total_chunks = 0
    failed_files = []
    errors = []
    
    all_documents: List[str] = []
    all_metadatas: List[Dict[str, Any]] = []
    all_ids: List[str] = []
    
    for file_path in files_to_process:
        try:
            doc = process_single_file(file_path)
            
            if doc is None:
                failed_files.append(file_path.name)
                continue
            
            # Chunk'ları hazırla
            for chunk in doc.chunks:
                chunk_id = generate_chunk_id(doc.file_path, chunk.chunk_index)
                
                all_documents.append(chunk.content)
                all_metadatas.append({
                    "source_file": doc.file_name,
                    "file_path": doc.file_path,
                    "file_type": doc.file_type,
                    "chunk_index": chunk.chunk_index,
                    "page_number": chunk.page_number,
                    **chunk.metadata
                })
                all_ids.append(chunk_id)
            
            processed_count += 1
            total_chunks += doc.total_chunks
            
        except Exception as e:
            error_msg = f"{file_path.name}: {str(e)}"
            failed_files.append(file_path.name)
            errors.append(error_msg)
            log_error(f"Dosya işleme hatası: {error_msg}", "vectorstore", error_detail=str(e))
    
    # Tüm chunk'ları bir seferde vektör veritabanına ekle
    if all_documents:
        try:
            rag_service.add_documents(
                documents=all_documents,
                metadatas=all_metadatas,
                ids=all_ids
            )
            log_system_event(
                "INFO",
                f"Vektör veritabanı güncellendi: {processed_count} dosya, {total_chunks} chunk",
                "vectorstore"
            )
        except Exception as e:
            error_msg = f"Vektör veritabanı güncelleme hatası: {str(e)}"
            errors.append(error_msg)
            log_error(error_msg, "vectorstore", error_detail=str(e))
            return BuildResult(
                success=False,
                processed_files=processed_count,
                total_chunks=total_chunks,
                failed_files=failed_files,
                errors=errors
            )
    
    return BuildResult(
        success=len(errors) == 0,
        processed_files=processed_count,
        total_chunks=total_chunks,
        failed_files=failed_files,
        errors=errors
    )


def add_file_to_vectorstore(file_path: Path) -> Dict[str, Any]:
    """
    Tek bir dosyayı vektör veritabanına ekler (incremental).
    Mevcut veritabanını silmez.
    
    Args:
        file_path: Eklenecek dosya
        
    Returns:
        İşlem sonucu
    """
    try:
        doc = process_single_file(file_path)
        
        if doc is None:
            return {
                "success": False,
                "error": f"Dosya işlenemedi: {file_path.name}"
            }
        
        # Chunk'ları hazırla
        documents = []
        metadatas = []
        ids = []
        
        for chunk in doc.chunks:
            chunk_id = generate_chunk_id(doc.file_path, chunk.chunk_index)
            
            documents.append(chunk.content)
            metadatas.append({
                "source_file": doc.file_name,
                "file_path": doc.file_path,
                "file_type": doc.file_type,
                "chunk_index": chunk.chunk_index,
                "page_number": chunk.page_number,
                **chunk.metadata
            })
            ids.append(chunk_id)
        
        # Vektör veritabanına ekle
        rag_service = get_rag_service()
        added_count = rag_service.add_documents(documents, metadatas, ids)
        
        return {
            "success": True,
            "file_name": doc.file_name,
            "chunks_added": added_count,
            "metadata": doc.metadata
        }
        
    except Exception as e:
        log_error(f"Dosya ekleme hatası: {str(e)}", "vectorstore", error_detail=str(e))
        return {
            "success": False,
            "error": str(e)
        }

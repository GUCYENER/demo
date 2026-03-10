from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple

# Burada mevcut LLM wrapper'ını kullan.
# Örneğin app/core/llm.py içinde chat_completion, generate_text vb. varsa ona göre uyarlarsın.
from app.core.llm import chat_completion  # <- Bunu kendi fonksiyonuna göre güncelle


@dataclass
class SupportFlowResult:
    steps: List[str]
    cym_text: str
    logs: List[Tuple[str, str]]  # (role, content)


def _ask_llm(system_prompt: str, user_prompt: str) -> str:
    """
    LLM'e tek noktadan soru sormak için yardımcı fonksiyon.
    Kendi llm.py'ndeki fonksiyona göre içini düzenleyebilirsin.
    """
    # Örnek bir arayüz; senin wrapper'ın değişik olabilir
    response = chat_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    return response.strip()


def _parse_steps_from_text(text: str) -> List[str]:
    """
    LLM cevabından numaralı adımları sade listeye çevirir.
    Çok mükemmel olmak zorunda değil, hackathon için yeterli.
    """
    lines = [l.strip("-• ") for l in text.splitlines() if l.strip()]
    steps = []
    buf = []

    for line in lines:
        if (
            any(
                line.startswith(prefix)
                for prefix in ("1.", "2.", "3.", "4.", "5.", "Adım", "ADIM")
            )
            and buf
        ):
            steps.append(" ".join(buf).strip())
            buf = [line]
        else:
            buf.append(line)

    if buf:
        steps.append(" ".join(buf).strip())

    # Eğer hiç düzgün parse edemediysek en azından tek adım dön
    if not steps:
        steps = [text.strip()]

    return steps


def run_support_flow(description: str) -> SupportFlowResult:
    """
    Planner -> Worker -> Verifier -> Nihai Çözüm
    akışını tek fonksiyonda koordine eder.
    """

    # 1) Planner - genel plan
    planner_system = (
        "Sen bir L1 destek masasında PLANLAYICI rolündesin. "
        "Görevin, kullanıcının sorunu için yüksek seviyeli bir çözüm planı çıkarmak. "
        "Gereksiz detay yok, sadece net akış adımlarını yaz."
    )
    planner_user = (
        f"Kullanıcının sorunu:\n\n{description}\n\nLütfen izleyeceğimiz planı yaz."
    )
    planner_answer = _ask_llm(planner_system, planner_user)

    # 2) Worker - planı detaylandır
    worker_system = (
        "Sen L1 destek masasında ÇALIŞAN (WORKER) rolündesin. "
        "Planner tarafından üretilen planı alıp, son kullanıcı için adım adım uygulanabilir talimata dönüştür."
        "Her adım net, sırayla uygulanabilir olsun."
    )
    worker_user = (
        f"Kullanıcının sorunu:\n\n{description}\n\n"
        f"Planner planı:\n{planner_answer}\n\n"
        "Lütfen bu plana göre son kullanıcı için adım adım çözüm adımları üret."
    )
    worker_answer = _ask_llm(worker_system, worker_user)

    # 3) Verifier - kontrol & sadeleştir
    verifier_system = (
        "Sen L1 destek masasında DOĞRULAYICI (VERIFIER) rolündesin. "
        "Worker'ın ürettiği adımları kontrol et, gereksiz olanları çıkar, sırayı düzelt ve netleştir. "
        "Çıktında sadece numaralı adımlar olsun."
    )
    verifier_user = (
        f"Kullanıcının sorunu:\n\n{description}\n\n"
        f"Worker adımları:\n{worker_answer}\n\n"
        "Lütfen son kullanıcıya verilecek nihai, numaralı çözüm adımlarını üret."
    )
    verifier_answer = _ask_llm(verifier_system, verifier_user)

    steps = _parse_steps_from_text(verifier_answer)

    # 4) ÇYM çağrı içeriği - IT jargonuyla kısa ve öz
    cym_system = (
        "Sen bir IT Service Desk uzmanısın. "
        "Aşağıdaki bilgileri kullanarak Çağrı Merkezi sistemine yazılacak KISA ve ÖZ bir talep özeti üret. "
        "Format:\n"
        "📋 Konu: [Tek satırda konu başlığı]\n"
        "📝 Talep: [Kullanıcının talebi - IT jargonuyla]\n"
        "✅ Önerilen Çözüm: [Kısa çözüm özeti]\n\n"
        "Gereksiz detay yazma. Sadece öz bilgi olsun."
    )
    cym_user = (
        f"Kullanıcının sorunu:\n{description}\n\n"
        f"Nihai çözüm adımları:\n{verifier_answer}\n\n"
        "Lütfen ÇYM sistemi için kısa ve öz çağrı metnini üret."
    )
    cym_text = _ask_llm(cym_system, cym_user)

    logs = [
        ("planner", planner_answer),
        ("worker", worker_answer),
        ("verifier", verifier_answer),
        ("final", "\n".join(steps)),
    ]

    return SupportFlowResult(steps=steps, cym_text=cym_text, logs=logs)

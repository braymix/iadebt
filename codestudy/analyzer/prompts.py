"""Template di prompt (flusso IBRIDO tecnico+dominio) e parsing dell'output.

I prompt chiedono un JSON con una struttura fissa; il parsing e' robusto a
testo attorno al JSON e a fence markdown. Il contratto e' identico per ogni
provider, cosi' l'output non dipende dal motore.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from ..models import AnalysisResult, Unit
from ..stack import StackRule


_JSON_CONTRACT = """\
Rispondi ESCLUSIVAMENTE con un oggetto JSON valido (nessun testo prima o dopo,
niente fence markdown) con ESATTAMENTE queste chiavi:
{
  "summary": "1-2 frasi: cosa fa/come e' cambiato questo blocco",
  "technical_flow": "flusso tecnico di esecuzione: chi chiama chi, come si muovono i dati dalla request alla persistenza e ritorno, dove si valida/blocca e perche'",
  "business_flow": "flusso di business/dominio: cosa succede per l'utente e quali regole/vincoli di dominio governano l'operazione",
  "flashcards": [
    {"front": "domanda", "back": "risposta", "tags": "tag1;tag2"}
  ],
  "mermaid": "un diagramma Mermaid (sequenceDiagram o flowchart) SENZA fence, che mostra le catene di chiamate del pezzo analizzato",
  "notes_markdown": "note di studio discorsive in markdown (tecnico + dominio)"
}

Regole per le flashcard (NON negoziabili):
- Devono testare la COMPRENSIONE DEL FLUSSO, non la memoria a pappagallo.
- VIETATO "Cosa fa la funzione X?". Preferisci domande che costringono a
  ricostruire il flusso, es: "Se arriva una richiesta senza token valido, in
  quale layer viene bloccata e perche'?" oppure "Quale regola di dominio
  impedisce di X, e dove e' implementata?".
- Collega esplicitamente regola di business <-> controllo tecnico che la implementa.
- Genera da 3 a 6 flashcard per blocco.
- Il Mermaid deve essere sintatticamente valido.
"""


_JSON_CONTRACT_MINIMAL = """\
La modifica e' PICCOLA: sii ESSENZIALE, niente riempitivi. Rispondi ESCLUSIVAMENTE
con un oggetto JSON valido (nessun testo prima o dopo, niente fence markdown) con
ESATTAMENTE queste chiavi:
{
  "summary": "1 frase asciutta: cosa cambia in concreto e perche' conta",
  "technical_flow": "",
  "business_flow": "",
  "flashcards": [
    {"front": "domanda sull'effetto/motivo del cambio", "back": "risposta breve", "tags": "tag"}
  ],
  "mermaid": "",
  "notes_markdown": ""
}

Regole per le modifiche piccole (NON negoziabili):
- Lascia VUOTI `technical_flow`, `business_flow`, `mermaid`, `notes_markdown`: una
  modifica piccola non li giustifica. Riempi `notes_markdown` (1 riga) SOLO se c'e'
  un'insidia o un vincolo non ovvio.
- 1 sola flashcard (2 al massimo, e solo se il cambio tocca due concetti distinti).
  Deve testare la comprensione dell'EFFETTO del cambio, non "cosa fa X".
- Se non c'e' nulla di interessante da imparare, dillo nel summary e resta minimale.
"""


def _system_preamble(rule: StackRule) -> str:
    hint = rule.flow_hint or "Analisi generica basata sul diff/sorgente."
    return (
        "Sei un tutor che aiuta uno sviluppatore a capire davvero come funziona "
        "il proprio codice (spesso generato con AI), tramite richiamo attivo.\n\n"
        f"Contesto di stack rilevato: {rule.name} (linguaggio: {rule.language}).\n"
        f"{hint}\n"
    )


def build_prompt(unit: Unit, rule: StackRule) -> str:
    """Costruisce il prompt completo per una unita' di lavoro.

    Per i delta piccoli (`unit.extra["minimal"]`) usa un contratto ridotto: solo
    riassunto secco e una flashcard, cosi' le spiegazioni restano proporzionate al
    peso della modifica.
    """
    contract = _JSON_CONTRACT
    if unit.kind == "file_delta":
        minimal = bool(unit.extra.get("minimal"))
        if minimal:
            contract = _JSON_CONTRACT_MINIMAL
            task = (
                f"Analizza il DIFF (piccolo) del file `{unit.title}`. Spiega in modo "
                "essenziale cosa cambia e perche'; niente flusso completo ne' mappe."
            )
        else:
            task = (
                f"Analizza il DIFF del file `{unit.title}` sul range di commit indicato. "
                "Spiega come e' cambiato il flusso (tecnico e di dominio)."
            )
        body = f"DIFF:\n```diff\n{unit.payload}\n```"
    elif unit.kind == "file_summary":
        task = (
            f"Analizza il SORGENTE del file `{unit.title}`. Ricostruisci il flusso "
            "di esecuzione e le regole di dominio che vi passano."
        )
        body = f"SORGENTE:\n```\n{unit.payload}\n```"
    elif unit.kind == "dir_summary":
        task = (
            f"Questi sono i riassunti dei file del modulo `{unit.title}`. Sintetizza "
            "il ruolo del modulo, il flusso interno e come si collega al resto."
        )
        body = f"RIASSUNTI DEI FILE:\n{unit.payload}"
    elif unit.kind == "architecture":
        task = (
            "Questi sono i riassunti dei moduli di alto livello e i punti d'ingresso. "
            "Produci una mappa dell'ARCHITETTURA MACRO: componenti principali, punti "
            "d'ingresso, e il flusso end-to-end di una richiesta tipica."
        )
        body = f"RIASSUNTI DEI MODULI:\n{unit.payload}"
    else:
        task = f"Analizza il seguente contenuto (`{unit.title}`)."
        body = unit.payload

    return (
        f"{_system_preamble(rule)}\n"
        f"COMPITO: {task}\n\n"
        f"{body}\n\n"
        f"{contract}"
    )


def parse_result(raw: str) -> AnalysisResult:
    """Estrae l'AnalysisResult dal testo grezzo del provider, in modo robusto."""
    obj = _extract_json(raw)
    if obj is None:
        # fallback: nessun JSON => metti tutto nelle note, zero flashcard fittizie
        return AnalysisResult(
            summary="(risposta non strutturata del provider)",
            notes_markdown=raw.strip(),
        )
    return AnalysisResult.from_obj(obj)


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    s = text.strip()
    # 1) fence ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL)
    if m:
        cand = m.group(1)
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            pass
    # 2) JSON puro
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # 3) primo '{' ... ultimo '}' bilanciato-ish
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        cand = s[start : end + 1]
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            return None
    return None

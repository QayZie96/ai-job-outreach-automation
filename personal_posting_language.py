"""Conservative deterministic language gate for personal job postings.

Only description/body text is evaluated, never country, company, URL or title.
An unsupported *predominant* posting language is grounds for excluding a job
from this English/Greek job search. Uncertain/mixed/short text stays visible.
No API calls, LLMs, external models, downloads or runtime dependencies.
"""
from __future__ import annotations

from collections import Counter
import re


# Distinctive common function words and job-posting prose, not product or
# technical terminology. Avoid collisions such as English "in", "die", "is".
_CUES = {
    "English": """the and for with from this that they their there which your you our
        we are will would should must have has been were being looking join
        opportunity responsibilities requirements skills experience ability
        across work working company position applicant candidates team
        you'll we're you'll need what who how where about including
        we're their these those provide support manage
        """,
    "German": """und der das den dem des ein eine einen einer einem wir du dich dir deine deinen
        ihr ihre ihren unseren unsere unserem unser für mit bei auf von zur zum im ist sind
        werden wird kannst möchtest haben können nicht auch sich als über hier sowie
        suchen bieten gemeinsam dich freuen freuen uns bringen berufserfahrung
        erfahrung voraussetzungen kenntnisse bewerbung stellenbeschreibung
        mitarbeiter innen
        """,
    "Dutch": """het een voor van wij jij jouw onze ons deze dit die dat als bij zijn werken
        wordt worden zoeken hebben hebt graag jouw naar ook maar niet er
        om over waar welke kunnen willen iemand meer allemaal functie
        solliciteren verantwoordelijkheden ervaring opdracht zorg zorgen
        """,
    "French": """nous vous votre vos pour avec dans sur une des les aux notre nos leur
        leurs sont est êtes être cette ces ainsi cherche recherchons poste
        équipe expérience compétences travail travaillons opportunité
        rejoindre souhaitez votre seront serez missions responsabilités
        vous êtes avez devez
        """,
    "Spanish": """para con por una unas unos desde sobre nuestro nuestra nuestros nuestras
        buscamos estamos trabajo equipo experiencia conocimientos requisitos
        responsabilidades funciones empresa tendrás necesitas puedes
        buscamos somos ofrecer ofrecemos queremos buscamos candidatos
        tendrás ser desarrollar trabajar del los las será puedes
        """,
    "Portuguese": """para com uma umas uns dos das nosso nossa nossos nossas pela pelo
        pela trabalho experiência requisitos equipa equipe você vocês suas
        nossos estamos somos procuramos procuramos terá queremos competências
        responsabilidades oportunidades emprego funções através
        desenvolvimento empresa candidatar-se colaboração
        """,
    "Italian": """per con una uno delle degli della nello nella siamo nostri nostre nostra
        nostro lavoro esperienza requisiti competenze ricerca cerchiamo
        sarà responsabilità ruolo azienda hai vuoi capacità attività
        principali gestione clienti candidatura conoscenza insieme
        delle posizione offriamo opportunità
        """,
    "Polish": """pracy praca twoje naszego naszej naszym jesteśmy będziesz będziemy
        oferujemy poszukujemy wymagania doświadczenie obowiązki stanowisko
        zespołu zespołem oraz które który również także możesz współpracy
        projektów zarządzanie naszych ciebie przez rozwój umiejętności
        zakres odpowiedzialności aplikuj pracowników
        """,
    "Swedish": """och att som med för från vara har vi vår våra dina din du dig
        denna detta söker jobbet tjänsten erfarenhet arbetsuppgifter
        erbjudande arbetar tillsammans möjlighet ansvar kommer
        arbetar kunskap ansökan företaget du får
        """,
    "Norwegian": """og som med for fra være du vi vår våre din dine denne dette
        søker stillingen arbeidsoppgaver erfaring arbeid ønsker
        mulighet ansvaret ansatte sammen samarbeid kunnskap søknad
        arbeidsmiljø jobbe hos oss
        """,
    "Danish": """og som med for fra være vi vores din dine du dig denne dette
        søger stillingen arbejdsopgaver erfaring arbejde ønsker
        mulighed ansvar sammen samarbejde kompetencer virksomheden
        ansøgning hos os
        """,
    "Finnish": """ja että sinulla meidän sinä olet sinun työtä työpaikka tehtävä
        tehtävässä kokemusta osaamista etsimme haemme tarjoamme
        mahdollisuus työskentelet yrityksen hakemuksen vastuulla
        yhteistyössä asiakkaiden kanssa myös sekä
        """,
    "Turkish": """ve için olarak deneyim iş çalışma şirketimiz ekip arıyoruz
        aramaktayız başvurular sorumluluklar gereksinimler
        tecrübe sahip olan çalışma alanında adaylar
        müşterilerimiz ile veya olmak üzere bir bizim
        """,
    "Romanian": """și pentru care cu experiență responsabilități cerințe echipa
        nostru noastră suntem căutăm alături compania oferim
        cunoștințe abilități trebuie postul muncă activități
        vei avea din această domeniul
        """,
}


_CUES = {lang: frozenset(words.split()) for lang, words in _CUES.items()}
_WORDS = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)
_ONLY_ENGLISH = (
    re.compile(p, re.I)
    for p in (
        r"\benglish\s+(?:is|as)\s+(?:the\s+)?(?:only|sole|exclusive)\s+"
        r"(?:required\s+)?(?:working|work|business|company|team)\s+language\b",
        r"\b(?:only|sole|exclusive)\s+(?:required\s+)?(?:working|work|business)\s+"
        r"language\s+(?:is|:)\s+english\b",
        r"\bworking\s+language\s+(?:is|:)\s+(?:exclusively|only)\s+english\b",
        r"\b(?:arbeitssprache|unternehmenssprache|teamsprache)\s+"
        r"(?:ist|:)\s+(?:ausschließlich|ausschliesslich|nur)\s+englisch\b",
        r"\b(?:ausschließlich|ausschliesslich|nur)\s+englisch\s+"
        r"(?:als\s+)?(?:arbeitssprache|erforderlich)\b",
        r"\b(?:seule|unique)\s+langue\s+de\s+travail\s+(?:est|:)\s+l['’]anglais\b",
        r"\bla\s+langue\s+de\s+travail\s+(?:est|:)\s+"
        r"(?:uniquement|exclusivement)\s+l['’]anglais\b",
    )
)
_ONLY_ENGLISH = tuple(_ONLY_ENGLISH)


def _dominant_script(text: str) -> str | None:
    # Script rule applies only to overwhelmingly non-Latin bodies and never
    # classifies Greek as unsupported.
    counts = Counter()
    for ch in text[:12000]:
        if not ch.isalpha():
            continue
        cp = ord(ch)
        if 0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF:
            counts["Greek"] += 1
        elif (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF):
            counts["CJK"] += 1
        elif 0x3040 <= cp <= 0x30FF:
            counts["Japanese"] += 1
        elif 0xAC00 <= cp <= 0xD7AF:
            counts["Korean"] += 1
        elif 0x0400 <= cp <= 0x052F:
            counts["Cyrillic"] += 1
        elif 0x0600 <= cp <= 0x06FF:
            counts["Arabic"] += 1
        elif 0x0590 <= cp <= 0x05FF:
            counts["Hebrew"] += 1
        elif 0x0900 <= cp <= 0x097F:
            counts["Devanagari"] += 1
        else:
            counts["Latin/other"] += 1
    total = sum(counts.values())
    if total < 120:
        return None
    # Mixed Greek + Latin is supported; skip ambiguous multilingual bodies.
    if counts["Greek"] / total >= 0.18:
        return None
    script, amount = max(counts.items(), key=lambda item: item[1])
    if script not in ("Greek", "Latin/other") and amount >= 100 and amount / total >= 0.52:
        return script
    return None


def unsupported_posting_language(description: str) -> tuple[str | None, str]:
    """Return (unsupported predominant language or None, concise evidence).

    Positive detection is intentionally stricter than standard language ID.
    The result is a *user-defined application filter*, not proof that the
    employer formally mandates that language.
    """
    text = str(description or "")[:12000]
    script = _dominant_script(text)
    if script:
        return script, "Predominantly unsupported writing system"

    tokens = _WORDS.findall(text.casefold())
    if len(tokens) < 45:
        return None, "Too little language evidence"
    counts = Counter(tokens)
    hits = {lang: sum(counts[w] for w in clues) for lang, clues in _CUES.items()}
    english = hits.pop("English")
    leader = max(hits, key=hits.get)
    winner = hits[leader]
    second = max((v for k, v in hits.items() if k != leader), default=0)
    distinct = len(_CUES[leader] & counts.keys())

    # A meaningful English section prevents a foreign-only conclusion.
    # Some languages share function words; requiring dominant margin and
    # independent cues avoids misclassification from business terminology.
    if (winner < 9 or distinct < 5 or winner / len(tokens) < 0.09
            or winner < english * 2.2 + 3 or winner < second * 1.35 + 3):
        return None, "Mixed, English/Greek, or insufficient language evidence"
    if any(p.search(text) for p in _ONLY_ENGLISH):
        return None, "Explicit English-only working-language exception"
    return leader, f"Predominantly {leader} description; lexical evidence {winner}/{len(tokens)} words"

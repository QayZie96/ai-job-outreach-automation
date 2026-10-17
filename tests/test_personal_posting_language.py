"""Auditable deterministic EN/GR posting-language exclusion regressions.

No live providers, AI, Sheets, network or extra language models.
"""
import unittest

import personal_discovery as d
from personal_posting_language import unsupported_posting_language as detect


GERMAN = (
    "Über uns: Wir suchen eine engagierte Person für unser Unternehmen und "
    "bieten dir eine spannende Aufgabe in unserem Team. Du möchtest mit uns "
    "die digitale Zukunft gestalten? Bei uns kannst du deine Erfahrung "
    "einbringen und mit unseren Kolleginnen und Kollegen gemeinsam "
    "an spannenden Projekten arbeiten. Wir freuen uns auf deine Bewerbung. "
)
DUTCH = (
    "Wij zoeken iemand voor deze functie die graag met onze team werken wil. "
    "Je hebt ervaring met het beheren van de webshop en met een nieuw product. "
    "Wij bieden je een kans om in ons bedrijf aan deze opdracht te werken. "
    "Ook willen wij samen met jou naar onze klanten kijken en zorgen voor de "
    "verantwoordelijkheden van de online winkel. "
)
FRENCH = (
    "Nous recherchons une personne pour rejoindre notre équipe dans notre "
    "entreprise. Vous aurez des responsabilités avec nos clients et vous "
    "travaillerez dans cette équipe avec votre expérience. Nous souhaitons "
    "offrir une opportunité pour votre développement et vos compétences. "
    "Vous êtes motivé pour travailler avec nous et pour ce poste. "
)
SPANISH = (
    "Buscamos una persona para nuestro equipo de operaciones y para "
    "trabajar con nuestra empresa. Ofrecemos una oportunidad de trabajo "
    "con responsabilidades y funciones. Tendrás experiencia con nuestros "
    "clientes, conocimientos del mercado, y puedes desarrollar la "
    "gestión de proyectos con nuestro equipo. "
)
ENGLISH = (
    "We are looking for an operations analyst to join our company and "
    "work with the team to support product data. The position requires "
    "experience with our marketplace catalogue and you will manage "
    "pricing across different markets. Our responsibilities include "
    "working with partners, reporting data, and building better "
    "processes for customers. "
)
GREEK = (
    "Αναζητούμε συνεργάτη για την ομάδα ηλεκτρονικού εμπορίου της εταιρείας "
    "μας. Η θέση αφορά τη διαχείριση προϊόντων, την ανάλυση δεδομένων, "
    "τη συνεργασία με προμηθευτές και τη βελτίωση των διαδικασιών. "
    "Προσφέρουμε ευκαιρίες εκπαίδευσης και επαγγελματικής ανάπτυξης. "
)


def job(description, *, source="Adzuna"):
    return {
        "source": source, "source_job_id": "language-1",
        "job_title": "Marketplace Operations Specialist",
        "company_name": "Sample", "location": "Berlin, Deutschland",
        "remote": None, "location_restrictions": [], "timezone_restrictions": [],
        "job_description": description,
        "job_url": "https://www.adzuna.de/details/123",
        "created_at": "2026-10-17", "job_types": [], "tags": [],
    }


class PostingLanguageTests(unittest.TestCase):
    def test_unsupported_languages_detected_with_realistic_prose(self):
        for lang, sample in (
            ("German", GERMAN), ("Dutch", DUTCH),
            ("French", FRENCH), ("Spanish", SPANISH),
        ):
            with self.subTest(lang=lang):
                code, evidence = detect(sample * 3)
                self.assertEqual(code, lang, evidence)

    def test_english_and_greek_are_supported(self):
        for text in (ENGLISH * 3, GREEK * 3,
                     ENGLISH + GREEK + ENGLISH,
                     "<p>Marketplace Operations in Berlin</p>"):
            with self.subTest(text=text[:28]):
                self.assertIsNone(detect(text)[0])

    def test_short_ambiguous_does_not_silently_disappear(self):
        for text in ("Wir suchen", "Manage products", "", "Marketplace de la vente"):
            self.assertIsNone(detect(text)[0])

    def test_mixed_description_keeps_uncertainty(self):
        # German office introduction but English actual responsibilities.
        text = GERMAN + ENGLISH * 4
        self.assertIsNone(detect(text)[0])

    def test_english_sole_working_language_exception(self):
        text = GERMAN * 4 + " Arbeitssprache ist ausschließlich Englisch."
        lang, why = detect(text)
        self.assertIsNone(lang)
        self.assertIn("English-only", why)

    def test_english_language_mentioned_but_not_only_is_not_exception(self):
        lang, _ = detect(GERMAN * 4 + " Fluent English required.")
        self.assertEqual(lang, "German")

    def test_german_company_english_ad_stays_in_pipeline(self):
        kept, count, _ = d.screen_candidates([job(ENGLISH * 3)])
        self.assertEqual(len(kept), 1)
        self.assertEqual(count.get("posting_language_excluded", 0), 0)

    def test_foreign_post_hard_excluded_and_audited(self):
        row = job(GERMAN * 3)
        audit = []
        kept, count, rej = d.screen_candidates([row], audit=audit)
        self.assertEqual(kept, [])
        self.assertEqual(count.get("posting_language_excluded", 0), 1)
        self.assertEqual(rej.get("Adzuna:posting_language", 0), 1)
        self.assertEqual(audit[0]["screen_outcome"], "posting_language_excluded")
        self.assertIn("Posting language not supported: German",
                      audit[0]["eligibility_reason"])

    def test_greek_job_not_excluded(self):
        row = job(GREEK * 4, source="Himalayas")
        kept, count, _ = d.screen_candidates([row])
        self.assertEqual(len(kept), 1)
        self.assertEqual(count.get("posting_language_excluded", 0), 0)

    def test_mixed_or_unknown_stays_reviewable(self):
        kept, count, _ = d.screen_candidates([job(GERMAN + ENGLISH * 4)])
        self.assertEqual(len(kept), 1)
        self.assertEqual(count.get("posting_language_excluded", 0), 0)

    def test_non_latin_unsupported_script_but_not_greek(self):
        arabic = ("نبحث عن شخص للعمل مع فريقنا في الشركة ونتطلع إلى التقديم "
                  "والخبرة في مجال التجارة الإلكترونية وخدمة العملاء " * 8)
        foreign, _ = detect(arabic)
        self.assertEqual(foreign, "Arabic")
        self.assertIsNone(detect(GREEK * 4)[0])


if __name__ == "__main__":
    unittest.main()

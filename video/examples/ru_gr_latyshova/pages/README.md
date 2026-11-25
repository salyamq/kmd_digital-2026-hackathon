# Chapter pages for the GR demo (not in git)

The demo cites **М.Г. Латышова, «Практическое руководство по интерпретации диаграмм геофизических исследований
скважин», 3-е изд., М.: Недра, 1991 — гл. III, § 12 «Метод естественного гамма-излучения ГМ»**.
The book is copyrighted, so its page text is not committed. Re-create it from the PDF the hackathon provided:

```bash
python scripts/extract_pages.py --pdf "<path>/Латышова_1991.pdf" --find "ГАММА-ИЗЛУЧЕНИЯ"     # -> p065 … p069
python scripts/extract_pages.py --pdf "<path>/Латышова_1991.pdf" --pages 64-69 --out examples/ru_gr_latyshova/pages
```

This writes `p064.txt … p069.txt` (one file per PDF page, `pdftotext` text layer; pypdf fallback).
Page numbers in `../node.json` are these **PDF page indices** of the provided (retyped) file — the printed page
numbers of the paper edition are not in it. Without these files the video still builds, but QA reports
`claims_verified: fail (no_pages)` and the video gets the DRAFT mark.

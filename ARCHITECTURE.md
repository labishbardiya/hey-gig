# Hey GIG system decisions

## Demo workflow

The USB camera feeds the Mac scanner via the Pi. The wearer captures and reviews
pages, exports a searchable PDF, and sees it in Library. A share draft identifies
the document and recipient. Its decision appears in Activity. This local
workflow uses Tesseract, qpdf, SQLite, and the browser HUD.

## Document extraction

| Path | Deliverable | Trade-off |
| --- | --- | --- |
| Tesseract + qpdf | Searchable PDF retaining the page image | Small local dependency footprint. Weak on blur, reading order, handwriting, and dense tables. Actual sample model numbers were misread. |
| OpenCV before OCR | Page boundary, stable hold, crop, perspective correction and duplicate checks | Works without model inference. Low-contrast pages and clutter can defeat corner detection. Keep manual capture and access to the original frame. |
| PP-OCRv5 / PP-StructureV3 | Regional OCR, reading order, tables and formula extraction | More dependencies and compute. Output needs separate validation, especially cell structure and part numbers. |
| PaddleOCR-VL | Structured extraction candidate for difficult pages | Benchmark claims come from the authors and do not establish performance on the Pi camera. Budget for model latency, memory, and review of incorrectly reconstructed text or tables. |

Retain the searchable PDF path as the baseline. Add structured extraction as a
separate result with page references and source crops. Compare engines on the
same English, Hindi, mixed-language, table, skewed, and blurry pages from the USB
camera. Measure character and field accuracy, capture rejection, table cell
accuracy, latency and peak memory on both hosts. Report uncertain values for
review. Use a recapture prompt when the frame itself is unreadable.

Sources: [PaddleOCR technical report](https://arxiv.org/abs/2507.05595),
[PaddleOCR releases](https://github.com/PaddlePaddle/PaddleOCR/releases),
[Tesseract documentation](https://tesseract-ocr.github.io/).

## Build and verification order

1. Document capture and extraction. Add automatic page capture and cleanup,
   then benchmark structured parsing. Verify three differently formatted pages.
2. Local voice. Test PipeWire input/output, whisper.cpp transcription, a local
   llama.cpp model, and TTS with push-to-talk before duplex and interruption.
3. Companion. Use Kotlin and Jetpack Compose with authenticated HTTPS and
   live state events from the Mac backend. Test scan review, then approval from
   the tablet. A local browser HUD remains the Mac interface.
4. Privacy. Coordinate GPIO switch, media sessions, temporary buffers, and
   client status. Test fail-closed capture when the control connection drops.
   The Pi can end its Bluetooth audio stream through software.
5. Reminders and routines. Persist schedules in SQLite, normalize time zones,
   and recover due items after restart. Allowlist local routine actions.
6. Provider adapters. Add Drive, Telegram, photo picker, CALL-E, Maps, music,
   and GitHub in that order as demo needs dictate. Use typed requests, scoped
   credentials, consent, delivery state, and duplicate-send protection.
7. Additional modes. Add English/Hindi translation, visual Q&A, timestamped
   video guidance, food estimates, public research using god-scrape, watch
   readings and opt-in event highlights. Verify each with its own fixtures.
   Move model workers to the RTX PC and compare the same test set.

## Mac OCR comparison on one USB scan

Both engines received the same crop from the previously saved USB-camera
parts-list PDF. Timings are per image on the Mac CPU and exclude model setup
and downloads. This is a single qualitative comparison.

| Engine | Time | Observations |
| --- | --- | --- |
| Tesseract 5.5.4, English, PSM 6 | 0.28 s | Retained some camera-model lines omitted by PaddleOCR. Misread some small text and identifiers, including the Arducam kit number. |
| PaddleOCR 3.7.0, PP-OCRv5 mobile detection + English mobile recognition | 2.45 s, 2.42 s | Read Raspberry Pi 5 Model B, StarTech HDMM2M and PJRC Teensy 4.0 more clearly. Omitted some lines and still misread parts of the Arducam identifier. |

Keep Tesseract as the current export and word-geometry engine. Use multiple
camera captures with verified transcripts, including Hindi and dense tables,
before choosing a second engine. PP-StructureV3 and PaddleOCR-VL were not
benchmarked in this run.

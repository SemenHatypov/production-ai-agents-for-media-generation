# Capstone Proposal: Themed City Walking Tours (Berlin First)

> Draft, Module 1. Budget numbers use the course's L40S baselines and will be replaced with my own Homework 1 measurements.

## 1. Problem and User

- **Who is the user?** A traveller who wants a self-guided walk through a city on a theme they care about (the Berlin Wall, queer Berlin, Karl-Marx-Allee) instead of a generic top-10 list.
- **What does each run produce, and why does it matter?** Each run produces a set of walking tours. Every stop of a tour gets a short narration script, an audio track to listen to on the spot and an illustration in the tour's visual style. Each tour has its own look and narrator: muted concrete greys with a calm voice for the Berlin Wall, Weimar-era art deco with an upbeat voice for queer Berlin. Within a tour, every stop looks and sounds the same, so the tour feels like one product rather than a pile of assets.

## 2. Input Records (`CSV`)

- **Dataset source:** my own records about Berlin, a city I have visited. Other cities can be added later with the same schema. Stops come from openly licensed sources: Wikivoyage (lists and itineraries, CC BY-SA 4.0), Wikipedia (facts, CC BY-SA 4.0) and Wikidata (coordinates, CC0). The records hold only facts and links; source text is fetched at run time and not committed.
- **Schema:**
  - `data/tours.csv`: `tour_id`, `city`, `theme`, `style_prompt`, `voice`, `audience`
  - `data/stops_seed.csv`: `id`, `tour_id`, `order`, `name`, `wiki_lang`, `wiki_title` (hand-picked stops)
  - `data/stops.csv`, built from the seed by `scripts/build_stops.py`: `id`, `tour_id`, `order`, `name`, `lat`, `lon`, `source_url`, `wikidata_id`, `personal_note` (optional: one or two lines from my own visit, woven into the narration)
- **Target batch size:** 100 stops (image + speech). The prototype starts with the 5 Berlin tours below at about 10 stops each (49 stops in `data/stops.csv`). It reaches 100 by adding stops to these tours or adding more Berlin tours. Every tour has enough open material: the Wikivoyage Berlin district articles (Mitte, East Central, City West) and a Wikipedia article for most stops.

| # | Tour | Style | Voice |
|---|---|---|---|
| 1 | From Alexanderplatz to the Brandenburg Gate via Museum Island | Classical engraving, Prussian grandeur | Measured |
| 2 | The Berlin Wall: from Bernauer Straße to the East Side Gallery (walk + U-Bahn; the gallery is one stop, not individual murals) | Muted concrete greys, documentary photo | Calm, low |
| 3 | Karl-Marx-Allee: from Stalinallee to socialist modernism | Socialist-realist poster, bold reds | Confident |
| 4 | Queer Berlin: from Nollendorfkiez to Tiergarten | Weimar-era art deco with rainbow accents | Upbeat |
| 5 | Kurfürstendamm: West Berlin's showcase, from the Golden Twenties to the Cold War | Mid-century advertising poster | Lively |

## 3. GPU Media Models

| Role | Exact Model ID & Revision | Modality | Target GPU & Preset | Licence Link |
|---|---|---|---|---|
| `image` | `Efficient-Large-Model/Sana_1600M_1024px_diffusers` (`ac0da2ff55fbe434795be0dce883042e4d49e2fc`) | Text-to-image (`1024x1024` PNG) | `gpu-l40s-a` (`1gpu-8vcpu-32gb`), preemptible | [Apache-2.0 + Gemma terms](https://huggingface.co/Efficient-Large-Model/Sana_1600M_1024px_diffusers) |
| `speech` | `hexgrad/Kokoro-82M` (`f3ff3571791e39611d31c381e3a41a3af07b4987`) | Text-to-speech (MP3, 60–120 s per stop) | `gpu-l40s-a` (`1gpu-8vcpu-32gb`), preemptible | [Apache-2.0](https://huggingface.co/hexgrad/Kokoro-82M) |
| Optional `asr` | Whisper-family model, TBD | Speech-to-text, for the audio check | `gpu-l40s-a` | TBD |

Narration scripts come from an open instruct LLM on Nebius Token Factory (model TBD). It is the planner, not one of the GPU media models.

## 4. Pipeline & Quality Checks

- **Brief → Planner (LLM) → GPU Tools → Judge/Checks → Object Storage:**
  1. **Plan (LLM):** for each stop, read the source article and write a narration script (about 150–300 words) that fits the tour's theme and audience, links to the previous stop ("walk 300 m along the canal to…") and includes my `personal_note` if there is one. It also writes an `image_prompt` that combines the stop with the tour's `style_prompt`.
  2. **Fact check (LLM judge):** compare the script with the source article and reject unsupported claims.
  3. **Illustration (`image`):** Sana renders the stop in the tour's style, with a fixed seed per stop that is saved with the asset.
  4. **Narration (`speech`):** Kokoro reads the script with the tour's preset voice.
  5. **Store:** assets and a manifest go to S3-compatible Object Storage.
- **Async step:** illustrations and narrations run as Nebius Serverless Jobs over the whole batch. The agent submits them, keeps the job IDs and per-stop state in a manifest, and on restart skips stops that are already done.
- **Two acceptance criteria:**
  1. **Facts:** every factual claim in the script is supported by the stop's `source_url` article. The personal note is exempt but must be marked as personal.
  2. **Assets:** the narration lasts 60–120 s, and its transcript matches the script. The illustration has no readable text, watermark or sexualised content, and matches its tour's style, consistent with the other stops of the same tour.

## 5. Initial Budget Estimate (Lesson 1.5 Cost Model)

- **GPU hourly rate:** `gpu-l40s-a` in eu-north1, preemptible `$0.7492/h` (`$0.0002081/s`); on-demand `$1.5484/h` as the upper bound. Source: [Nebius pricing](https://docs.nebius.com/compute/resources/pricing), read 11 Nov 2026 in the course's lesson 01.
- **Marginal cost per asset (`c = rate × t_gen`):**
  - Image: `4.42 s` (course L40S baseline) → `c_image = $0.00092`
  - Speech: about `22 s` for 90 s of narration, scaled linearly from the course's `1.88 s` per 7.6 s of speech → `c_speech ≈ $0.0046` (to be measured)
- **Fixed startup + load per worker run (`F = rate × (t_start + t_ready)`):**
  - Image: `265 s` (from the course example) → `F_image = $0.055`
  - Speech: `242 s` (from the course example) → `F_speech = $0.050`
- **Total for the capstone batch** (100 stops + 20% retries = 120 generations per model, one Job per model):
  - Images: `$0.055 + 120 × $0.00092 = $0.17`
  - Narration: `$0.050 + 120 × $0.0046 = $0.61`
  - **GPU total: about `$0.77` preemptible, `$1.60` on-demand.** LLM calls for planning and judging come from the Token Factory credit and will be reported separately.

## Known Limitations

- The East Side Gallery murals are copyrighted works by living artists, so the tour treats the gallery as one stop and never asks the image model to reproduce a mural.
- Narration is in English, so German names (Gedenkstätte Berliner Mauer, Strausberger Platz) may be mispronounced.
- The Sana model card says it is intended for research use. Fine for a course project; check before any commercial use.
- Narration scripts are derived from CC BY-SA articles. Code is MIT; generated scripts and audio will be published under CC BY-SA with attribution.

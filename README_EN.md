# PPT Agent Skill

**[中文文档](README.md)**

> Simulate a top-tier PPT design company's workflow — from a single sentence to professional-grade presentations.

> **Expectations**: AI-generated PPTs reach 80-90% completion (solid structure, consistent style, data visualizations),
> but minor details (text overflow, spacing, occasional layout quirks) still need human review.
> Think of it as a **high-quality draft generator** — 25 min AI generation + 10 min human polish, instead of 8-16 hours from scratch.

## Showcase

> Example output: "PPT Agent Skill Cost Reduction" (Blue White business style, 10 pages, ~25 min end-to-end):

| Cover | Traditional vs AI |
|:---:|:---:|
| ![Cover](doc/showcase/slide_01.png) | ![Comparison](doc/showcase/slide_04.png) |

| 6-Step Pipeline | Efficiency Data |
|:---:|:---:|
| ![Pipeline](doc/showcase/slide_06.png) | ![Data Overview](doc/showcase/slide_08.png) |

| ROI Analysis | End Page |
|:---:|:---:|
| ![ROI](doc/showcase/slide_09.png) | ![End](doc/showcase/slide_10.png) |

## Workflow

```
One sentence → Interview → Research → Outline → Planning → Style + Images + HTML → Post-processing (SVG + PPTX)
```

| Step | Description | Tool |
|------|-------------|------|
| Step 1 | Requirements interview (7 questions, 3 layers) | Agent dialog |
| Step 2 | Web research | `web_search.py` (Brave + Tavily dual engine) |
| Step 3 | Outline (Pyramid Principle) | Prompt #2 |
| Step 4 | Content allocation + planning draft (batched to prevent truncation) | Prompt #3 + Bento Grid layout selection |
| Step 5 | Style + icon matching + images (opt-in) + HTML design | `icon_resolver.py` + `generate_image.py` (opt-in) + Prompt #4 |
| Step 6 | Post-processing | `html2svg.py` → `svg2pptx.py` |

## Key Features

| Feature | Description |
|---------|-------------|
| **6-Step Pipeline** | End-to-end automation simulating professional PPT design workflow |
| **Smart Search** | Brave + Tavily dual engine, zero-dependency Python script, auto-fallback |
| **AI Illustrations (Opt-in)** | Gemini native image generation, 16:9 widescreen, smart scoping (cover/section/end pages). Off by default, enabled on user request |
| **6 Preset Styles** | Corp Tech / MWC Expo / Flat Report / Flat Training / Sci-Tech Blue / Event Blue (distilled from real company templates) |
| **Lucide Icon System** | 1940 vector SVG icons, 19 PPT scene categories, smart CN/EN keyword matching (`icon_resolver.py`), mandatory step |
| **7 Bento Grid Layouts** | Flexible card-based layouts, content-driven layout selection |
| **Typography System** | 7-level font scale + CJK typesetting + 60-30-10 color rule |
| **8 Data Visualizations** | Progress bars / ring charts / sparklines / comparison bars / waffle charts / KPI cards (pure CSS/SVG) |
| **Pipeline Compatibility** | `pipeline-compat.md` documents all CSS → SVG → PPTX conversion pitfalls and correct patterns |
| **Fully Editable PPTX** | HTML → SVG → PPTX, right-click "Convert to Shape" in PPT 365 |
| **Cross-platform Portable** | All external capabilities (search/image/conversion) are standalone Python scripts + `.env` config, not tied to any Agent framework |

## Requirements

**Required:**
- **Python** >= 3.8
- **Node.js** >= 18 (Puppeteer + dom-to-svg require it; verify with `node --version` in your active shell)

**Install:**
```bash
pip install python-pptx lxml Pillow
```

> **Important**: Puppeteer downloads Chromium (~170MB) on first install, and dom-to-svg
> requires compilation. Pre-install before use to avoid long waits during Step 6:
> ```bash
> cd ppt-output && npm init -y && npm install puppeteer dom-to-svg
> ```
> `html2svg.py` will auto-install missing deps on first run, but the delay may cause timeouts.

**Fallback path (when dom-to-svg is unavailable):**

When Node.js < 18 or dom-to-svg installation fails, html2svg.py automatically falls back to Puppeteer PDF + pdf2svg (text becomes paths, NOT editable). This requires system-level pdf2svg:
```bash
# Debian/Ubuntu
sudo apt install pdf2svg

# CentOS/RHEL
sudo yum install pdf2svg
# Or use EPEL repository
sudo yum install epel-release
sudo yum install pdf2svg

# Windows
# Download precompiled version: https://github.com/jalios/pdf2svg-windows/releases
# Or use Chocolatey: choco install pdf2svg
```

**Optional (configure `.env`):**
```bash
cp .env.example .env
# Edit .env with your API keys:
# BRAVE_API_KEY=xxx       — Web search (Brave Search, free 2000 queries/month)
# TAVILY_API_KEY=xxx      — Web search + content extraction (Tavily)
# IMAGE_API_KEY=xxx       — AI illustrations (Gemini image generation)
# IMAGE_API_BASE=xxx      — Image API endpoint
# IMAGE_MODEL=xxx         — Image model name
```

## Directory Structure

```
ppt-agent-skill/
  SKILL.md                        # Agent workflow instructions (entry point)
  .env.example                    # Environment variable template
  references/
    prompts.md                    # Prompt template index
    prompts/                      # 5 standalone Prompt templates (loaded per step)
      prompt_1_survey.md          # Requirements interview (7 questions)
      prompt_2_outline.md         # Outline architect (Pyramid Principle)
      prompt_3_planning.md        # Content allocation & planning
      prompt_4_design.md          # HTML design generation
      prompt_5_notes.md           # Speaker notes (optional)
    style-system.md               # 6 preset styles + CSS variables + auto luminance
    bento-grid.md                 # 7 layout specs + 6 card types
    pipeline-compat.md            # HTML→SVG→PPTX pipeline compatibility rules
    icon-guide.md                 # Lucide icon system guide (19 category quick-ref)
    icons/                        # 1940 Lucide SVG icons
    icons/tags.json               # Icon tag index
    method.md                     # Core methodology
  scripts/
    web_search.py                 # Web search (Brave + Tavily dual engine)
    generate_image.py             # AI illustrations (Gemini native image gen)
    icon_resolver.py              # Smart icon matching (CN/EN keywords → Lucide SVG)
    extract_style.py              # Style extraction tool
    html_packager.py              # Merge multi-page HTML into paginated preview
    html2svg.py                   # HTML → SVG (dom-to-svg, editable text)
    svg2pptx.py                   # SVG → PPTX (OOXML native shapes)
  doc/
    showcase/                     # README showcase images
```

## Output

All artifacts are written to `ppt-output/{topic}_{date}/` (e.g. `ppt-output/AI_Safety_20260326/`).
Topic name is auto-extracted from user input (≤10 chars, illegal filename chars removed), date in `YYYYMMDD` format.

### Final Deliverables

| File | Format | Description |
|------|--------|-------------|
| `{topic}_{date}.pptx` | PPTX | Final presentation (right-click "Convert to Shape" in PPT 365 to edit) |
| `{topic}_{date}_preview.html` | HTML | Browser-viewable paginated preview with all pages |
| `svg/*.svg` | SVG | Per-page vector files, can also be dragged into PPT |

### Design Source Files

| File | Format | Description |
|------|--------|-------------|
| `slides/slide_XX.html` | HTML | Per-page HTML design, 1280x720px fixed canvas, all styles inlined |
| `images/slide_XX.png` | PNG | AI-generated illustrations, 16:9 widescreen |

### Intermediate Artifacts

| File | Description |
|------|-------------|
| `outline.json` | Outline structure (parts → chapters → pages) |
| `planning.json` | Planning draft (card types, layouts, content per page) |
| `style.json` | Style definition (color variables + fonts + gradients + decorations) |
| `queries.json` | Search query list |
| `search_results/*.json` | Search results |
| `images/batch.json` | Image generation batch definition |
| `notes.json` | Speaker notes (optional, injected into PPTX via `--notes`) |

## Usage

Describe your needs in conversation to trigger the full 6-step workflow:

```
You: "Make a PPT about X"
  → Step 1: Agent interviews for requirements
  → Step 2: web_search.py researches the topic
  → Step 3-4: Generates outline → planning draft
  → Step 5: Style selection + generate_image.py + per-page HTML design
  → Step 6: html2svg.py + svg2pptx.py → PPTX output
```

**Trigger Examples:**

| Scenario | What to Say |
|----------|-------------|
| Topic only | "Make a PPT about X" / "Create a presentation on Y" |
| With material | "Turn this document into slides" / "Make a PPT from this report" |
| With specs | "15-page dark tech style AI safety presentation" |
| Implicit | "I need to present to my boss about Y" / "Make training materials" |


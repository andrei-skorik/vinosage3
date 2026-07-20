"""Custom CSS injection for the Streamlit UI — presentation only, no business logic.

inject_css() renders one <style> block covering every visual task in
docs/vinosage-ui-tasks.md. All selectors target stable `data-testid`
attributes (never generated `st-emotion-cache-*` classes) or the
`.st-key-<key>` container class Streamlit emits for widgets created with a
`key=` (Streamlit >= 1.39; this project pins 1.58).
"""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@600;700&family=Public+Sans:wght@400;500;600&display=swap');

:root {
  --wine: #7B1E3D;
  --wine-dark: #5E1730;
  --wine-tint: #F7EEF1;
  --radius: 10px;
  --border: 1px solid rgba(0,0,0,0.10);
  --shadow-soft: 0 2px 8px rgba(0,0,0,0.06);
  --muted: #8A7A6E;
  /* Streamlit's default sidebar width; kept in sync with the real (possibly
     user drag-resized) width by the poller in inject_sidebar_width_watcher(). */
  --sidebar-width: 300px;
  /* Reserved width of a classic (non-overlay) scrollbar, if the page has one —
     also kept in sync by inject_sidebar_width_watcher(). Needed because
     position:fixed's "right" offset is measured against the full window
     width, while ordinary flowed content (the wine cards, etc.) is laid out
     in the scrollbar-narrowed content width; without this the voice button
     drifts right of the content it's meant to align with. */
  --scrollbar-width: 0px;
  /* stChatInput's own default rendered height (measured in DevTools) — New
     chat / language / voice all match it so the whole row reads as one line. */
  --bar-h: 60px;
  /* Language selector / voice input width — narrow on purpose (follow-up
     request: "half as long"); both previously centered short content (a
     2-letter code, an icon) inside a much wider box, leaving a large gap
     before the dropdown/expand chevron. 64px (a literal half of 120px)
     clipped the 2-letter language code down to a single truncated letter —
     the select's own internal padding plus its chevron leave less room for
     text than a plain width halving assumes, so this is the narrowest width
     that still shows "EN"/"DE" in full. */
  --bar-w: 80px;
}

/* ── Task 1: typography ────────────────────────────────────────────────── */
/* :not([data-testid="stIconMaterial"]) is required — Streamlit's expander/
   button icons are ligature glyphs (e.g. "keyboard_arrow_right") rendered
   via a dedicated icon font; overriding it here turns the ligature into
   literal text that overlaps the adjacent label. */
html, body, [data-testid="stAppViewContainer"] *:not([data-testid="stIconMaterial"]) {
  font-family: 'Public Sans', sans-serif;
}
h1, h2, h3 { font-family: 'Source Serif 4', serif; }

/* Links use the wine accent everywhere, not the Streamlit default blue. */
a { color: var(--wine); }

/* ── Sidebar density (follow-up request) ─────────────────────────────────── */
/* Streamlit's own <hr> (st.divider()) carries margin: 32px 0 by default —
   measured directly (DevTools). Compare that to the gap between two sidebar
   items that DON'T have a divider between them (How to use VinoSage / Admin):
   just ~33.6px total, entirely from Streamlit's own default inter-element
   spacing. Six dividers at 32px top+bottom each were the main contributor to
   the sidebar's excess scroll length. 4px reproduces that same ~33.6px total
   gap (computed from real measurements: 16px natural pre-gap + 4px margin +
   1px line + 4px margin + ~8.8px natural post-gap ≈ 33.8px) instead of the
   ~90px a full-margin divider was costing per section boundary. */
[data-testid="stSidebar"] hr {
  margin: 4px 0;
}
/* The sidebar logo sat ~36px below the collapse chevron (20px of the h1's
   own top padding, plus a ~16px gap Streamlit's own flex layout inserts
   between the collapse-button bar and the content below it) — moving it up
   against the chevron per the follow-up request. */
[data-testid="stSidebar"] h1 {
  padding-top: 0;
}

/* ── Task 2.2 (follow-up): "New chat" fixed in line with the chat input ─── */
/* position: sticky (an earlier approach) drifted upward at the end of a
   scroll because the scrollable container still had trailing content/padding
   below it. Anchoring to the viewport instead (position: fixed) removes it
   from the sidebar's document flow entirely, so it can never drift. It's now
   raised to bottom: 56px (see the Task 3 comment below for where that number
   comes from) to sit on the same row as chat_input instead of the sidebar
   floor — the scroll container's own padding-bottom keeps the real last
   sidebar item (Admin) from being hidden underneath it regardless. */
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
  padding-bottom: 150px;
}
/* Container spans the FULL strip from the true window bottom (bottom: 0) up
   past the button's row — not just the button's own 60px slice — because an
   earlier version anchored the opaque background at bottom: 56px too, the
   same as the button itself, leaving the 56px gap beneath it (down to the
   real window edge) uncovered; sidebar content scrolled underneath still
   showed through that sliver. padding-bottom pushes the button back up to
   the same visual row it already occupied, while the background now covers
   that entire lower strip, not just the button's own footprint. */
.st-key-new_chat_btn {
  position: fixed; bottom: 0; left: 0;
  width: var(--sidebar-width, 300px); height: calc(var(--bar-h) + 56px);
  padding: 0 16px 56px 16px;
  background: var(--secondary-background-color, #F6F1EC);
  z-index: 1001;
}
/* height:100% (an earlier attempt) silently no-ops here: Streamlit's own
   button wrapper divs between this container and the <button> don't carry
   an explicit height (only width:100% chains cleanly down that tree), so a
   percentage has nothing to resolve against. Sizing the button in the same
   absolute unit as --bar-h sidesteps that entirely. */
.st-key-new_chat_btn button { height: var(--bar-h); width: 100%; }

/* ── Task 2.4: button hierarchy ────────────────────────────────────────── */
.stButton > button { border-radius: var(--radius); }
.st-key-new_chat_btn button { background: var(--wine); border-color: var(--wine); }
.st-key-new_chat_btn button:hover { background: var(--wine-dark); border-color: var(--wine-dark); }

.st-key-logout_btn button,
.st-key-admin_lock_btn button,
.st-key-admin_unlock_btn button {
  border: none; background: transparent; color: var(--muted); font-size: 0.85rem;
}
.st-key-logout_btn button:hover,
.st-key-admin_lock_btn button:hover,
.st-key-admin_unlock_btn button:hover {
  color: var(--wine); background: var(--wine-tint);
}

/* ── Task 2 account card ───────────────────────────────────────────────── */
.st-key-account_card { border-radius: var(--radius); box-shadow: none; }

/* ── Task 2.3: segmented-control-style radio fallback (defensive; the code
   path prefers st.segmented_control on Streamlit >= 1.40) ────────────────── */
.st-key-answer_speed_wrap [role="radiogroup"] {
  display: inline-flex; border: var(--border); border-radius: var(--radius);
  padding: 2px; gap: 2px; background: #fff;
}
.st-key-answer_speed_wrap [role="radiogroup"] label {
  border-radius: calc(var(--radius) - 2px); padding: 2px 10px; margin: 0;
}

/* ── Task 3: fixed bottom bar (language + voice input) ─────────────────── */
/* --card-inset (80px) is Streamlit's own block-container gutter — measured
   directly against real content (the welcome heading, the suggestion-button
   row) at several sidebar widths and always exactly 80px on both sides,
   independent of viewport width. Wine recommendation cards live in that same
   main block container, so this is also THEIR left/right inset — anchoring
   lang/voice to sidebarWidth/viewport +/- this constant (follow-up request)
   keeps them edge-aligned with the cards as the sidebar is resized, rather
   than sitting at an arbitrary fixed offset that happens to look close. */
:root { --card-inset: 80px; }

[data-testid="stChatInput"] {
  border: var(--border); border-radius: var(--radius);
  box-shadow: var(--shadow-soft); background: #fff;
  /* chat_input is itself an ordinary child of that same main block container,
     so its own unstyled edges already sit at exactly --card-inset too; margin
     here is only the extra clearance (24px) from lang/voice's OWN edges (each
     --bar-w wide) beyond that shared baseline — see the lang/voice rule below
     for the matching math. Symmetric because lang/voice are the same width. */
  margin-left: 104px; margin-right: 104px;
}
[data-testid="stChatInput"]:focus-within { border-color: var(--wine); }

/* bottom: 56px is the actual measured offset (DevTools) between chat_input's
   own bottom edge and the window bottom — stable across viewport HEIGHTS
   because Streamlit's bottom bar is itself sticky to the window edge with
   fixed internal padding. Language/voice/New-chat now share this bottom AND
   stChatInput's own height (--bar-h) instead of only matching its center, so
   all four boxes' top/bottom edges line up exactly, reading as one row.
   --bar-w (64px, follow-up request "half as long") is deliberately narrow —
   both boxes previously centered their (short) content inside a much wider
   120px box, leaving a large empty gap before the dropdown/expand chevron. */
.st-key-bottom_bar_lang, .st-key-bottom_bar_voice {
  position: fixed; bottom: 56px; z-index: 1001;
  height: var(--bar-h); width: var(--bar-w);
}
/* left edge = sidebar width + --card-inset = the wine cards' own left edge. */
.st-key-bottom_bar_lang { left: calc(var(--sidebar-width, 300px) + var(--card-inset)); }
.st-key-bottom_bar_voice {
  /* width must be constrained — Streamlit's container is a block element
     that defaults to 100% width; left unconstrained, "right: <inset>" on a
     position:fixed box that still spans the whole viewport has no visible
     effect (the box's own left edge stays pinned near x:0). Right edge =
     --card-inset from the viewport edge = the wine cards' own right edge
     (the cards' right inset doesn't move with the sidebar, only their left
     edge does, since only the LEFT edge of the main content area shifts).
     + --scrollbar-width corrects for a real-browser-only scrollbar (see
     inject_sidebar_width_watcher()'s docstring) that isn't present in a
     headless check but visibly shifts this in a normal desktop browser. */
  right: calc(var(--card-inset) + var(--scrollbar-width, 0px));
}

/* height:100% (an earlier attempt) measured out to the selectbox's own
   intrinsic ~38px, not the 60px container — baseweb's select wrapper divs
   don't carry an explicit height for the percentage to resolve against.
   Forcing the same absolute --bar-h directly on the actual bordered box
   (confirmed via DevTools to be [data-baseweb="select"], not stSelectbox
   itself) plus flex-centering keeps the "EN" label vertically centered
   inside the now-taller box instead of stuck at its old top alignment. */
.st-key-bottom_bar_lang [data-baseweb="select"] {
  height: var(--bar-h) !important;
  display: flex !important; align-items: center !important;
}
.st-key-bottom_bar_lang [data-baseweb="select"] > div {
  height: 100%; display: flex; align-items: center;
}
.st-key-bottom_bar_lang [data-baseweb="select"] div[value] {
  font-weight: 700;
}

/* Same percentage-doesn't-resolve issue as above — measured at 55x40
   (its own shrink-to-fit icon-only size) instead of the container's
   full box, so both dimensions are pinned to absolute values here too. */
.st-key-bottom_bar_voice button {
  height: var(--bar-h) !important; width: var(--bar-w) !important;
  display: inline-flex !important; align-items: center !important; justify-content: center !important;
}
/* Icon-only per the follow-up request: the popover trigger's label text is
   kept in the Python call (for accessibility) but hidden here — Streamlit
   renders it as its own stMarkdownContainer sibling next to the (separate)
   icon element, so this can hide the text without touching the icon. */
.st-key-bottom_bar_voice [data-testid="stMarkdownContainer"] { display: none; }
/* The mic icon and the popover's own small "expand" chevron are BOTH
   [data-testid="stIconMaterial"] elements but sit in separate sibling divs
   (mic+label wrapper first, chevron wrapper second) — button > div > div
   :first-child reaches only the first, so doubling the mic icon (16px measured
   default -> 32px) doesn't also blow up the chevron next to it. */
.st-key-bottom_bar_voice button > div > div:first-child [data-testid="stIconMaterial"] {
  font-size: 32px;
}

/* ── Task 4: welcome / empty state ─────────────────────────────────────── */
.st-key-welcome {
  min-height: 55vh; display: flex; flex-direction: column; justify-content: center;
}
.st-key-suggestions button {
  border-radius: var(--radius); border: var(--border);
  box-shadow: none; transition: box-shadow .15s, transform .15s, border-color .15s, color .15s;
}
.st-key-suggestions button:hover {
  box-shadow: var(--shadow-soft); border-color: var(--wine); color: var(--wine);
}

/* ── Task 5.2: wine recommendation cards ───────────────────────────────── */
/* Keys are per-wine (wine_card_<wine_id>), so match the "st-key-wine_card_"
   prefix rather than a single fixed class. */
div[class*="st-key-wine_card_"] {
  background: var(--wine-tint); border-radius: var(--radius);
  border: var(--border); padding: 0.15rem 0.75rem;
}
/* 👍/👎 columns are shorter than the two-line title+price label, so they
   need the row's cross-axis alignment set explicitly to center — Streamlit's
   own vertical_alignment="center" on st.columns() computes centering against
   default (larger) container padding and doesn't reliably still center once
   this card's own tighter padding above changes the row's actual proportions. */
div[class*="st-key-wine_card_"] [data-testid="stHorizontalBlock"] {
  align-items: center !important;
}
/* The real cause of the persistent top-bias: render_feedback_buttons (chat_view.py)
   injects an invisible <span class="fbm...">, used by its own colour-toggle JS,
   right after each 👍/👎 button. Its OWN existing collapse rule (added via a
   separate JS-injected <style>, targeting stMarkdownContainer) does shrink
   that div itself to 0×0 — confirmed directly in DevTools — but Streamlit's
   vertical block still applies a flex `gap` BETWEEN each of its direct
   stElementContainer children (button's container, then the span's container)
   regardless of either child's own size, so the (invisible) gap survives even
   with the span's own box collapsed. Centering the row then centers a phantom
   ~16px-taller block (button + that surviving gap), biasing the visible
   button toward the top. Targeting the span's stElementContainer itself with
   display:none — one level up from the earlier collapse — removes it from
   the flex flow entirely, so it no longer participates in `gap` spacing at
   all; display:none doesn't remove it from the DOM, so the existing colour-
   toggle JS (which finds the span via plain querySelectorAll/closest,
   unaffected by CSS display) keeps working unchanged. */
div[data-testid="stElementContainer"]:has(span[class^="fbm"]) {
  display: none !important;
}

/* ── Task 5.3: de-emphasize Sources / Tools used metadata ──────────────── */
[data-testid="stChatMessage"] [data-testid="stExpander"] {
  border: none; background: transparent;
}
[data-testid="stChatMessage"] [data-testid="stExpander"] summary {
  color: var(--muted); font-size: 0.85rem;
}
[data-testid="stChatMessage"] [data-testid="stExpander"] summary:hover { color: var(--wine); }

/* ── Task 6: compact sidebar metrics ───────────────────────────────────── */
[data-testid="stSidebar"] [data-testid="stMetricValue"] { font-size: 1.15rem; }
[data-testid="stSidebar"] [data-testid="stMetricLabel"] { font-size: 0.75rem; color: var(--muted); }

/* ── Task 7: consistency pass ───────────────────────────────────────────── */
[data-testid="stExpander"] { border-radius: var(--radius); }
.stTextInput input, .stNumberInput input, .stSelectbox > div, .stMultiSelect > div {
  border-radius: var(--radius) !important;
}
.stTextInput input:focus, .stNumberInput input:focus {
  border-color: var(--wine) !important; box-shadow: 0 0 0 1px var(--wine) !important;
}
[data-testid="stButton"] button:focus-visible,
[data-testid="stChatInput"] textarea:focus {
  outline-color: var(--wine) !important; border-color: var(--wine) !important;
  box-shadow: 0 0 0 1px var(--wine) !important;
}
div[data-testid="stStatusWidget"] { display: none; }
</style>
"""


def inject_css() -> None:
    """Inject the app's custom stylesheet once per rerun.

    Called at the top of the entrypoint, right after st.set_page_config —
    Streamlit re-renders the whole script on every interaction, so this runs
    every rerun, but st.markdown de-duplicates identical <style> content in
    the DOM rather than piling up copies.
    """
    st.markdown(_CSS, unsafe_allow_html=True)


def inject_sidebar_width_watcher() -> None:
    """Keep --sidebar-width and --scrollbar-width in sync with the real page.

    --sidebar-width tracks the sidebar's real (possibly user drag-resized)
    width. Streamlit doesn't expose either of these as CSS variables, and
    unlike plain CSS injection this needs to run actual JS, which st.markdown
    can't do (scripts inserted via innerHTML never execute) — components.html
    renders into an iframe, whose scripts DO run and can still reach the
    parent document.

    An earlier version used a ResizeObserver attached once, guarded against
    re-attaching on every rerun. That measured the CORRECT width exactly once
    (whatever it happened to be when the guard first let it through) and then
    silently stopped tracking real resizes altogether — confirmed with a
    scripted drag-resize test: the CSS var stayed frozen at its initial value
    even across a subsequent Streamlit rerun that re-ran this exact function.
    components.html's iframe is torn down and recreated by Streamlit far more
    often than a per-page-load observer setup assumes, taking the observer
    down with it. Polling instead — cheap, and self-healing since it re-reads
    the DOM fresh on every tick rather than depending on any object (observer,
    element reference) surviving between reruns or iframe teardowns.

    --scrollbar-width fixes a real-browser-only bug: .st-key-bottom_bar_voice
    is anchored with `right: <inset>` against the whole viewport, while the
    wine cards / sources / tools boxes it's meant to align with are flowed
    inside Streamlit's OWN scrolling container — not the outer <html>/<body>,
    which never scrolls in a Streamlit app (confirmed: document.documentElement
    .scrollHeight there equals its clientHeight even with a full page of chat
    history). The actual scroller is the <section data-testid=
    "stAppScrollToBottomContainer" class="stMain ...">. In a real desktop
    browser with a classic (space-reserving) scrollbar, once that section's
    content overflows, its own clientWidth shrinks below its offsetWidth by
    the scrollbar's width — narrowing everything flowed inside it — while the
    voice button, anchored to the untouched outer viewport, doesn't shrink to
    match, and drifts right of the content by exactly that difference. A
    first attempt compared window.innerWidth against documentElement's
    clientWidth instead (the "normal" way to detect a page-level scrollbar)
    and always measured 0 here, precisely because it isn't the outer page
    that scrolls in this app.
    """
    components.html(
        """
        <script>
        (function() {
            var doc = window.parent.document;
            function apply() {
                var el = doc.querySelector('[data-testid="stSidebar"]');
                if (el) {
                    doc.documentElement.style.setProperty(
                        '--sidebar-width', el.getBoundingClientRect().width + 'px'
                    );
                }
                var mainEl = doc.querySelector('[data-testid="stAppScrollToBottomContainer"]');
                var scrollbarWidth = mainEl ? (mainEl.offsetWidth - mainEl.clientWidth) : 0;
                doc.documentElement.style.setProperty(
                    '--scrollbar-width', Math.max(0, scrollbarWidth) + 'px'
                );
            }
            apply();
            if (window.parent.__vinoSidebarInterval) {
                clearInterval(window.parent.__vinoSidebarInterval);
            }
            window.parent.__vinoSidebarInterval = setInterval(apply, 400);
        })();
        </script>
        """,
        height=0,
    )

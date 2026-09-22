# Search overview design audit

Historical design notes from the initial interface review. Test counts below
record that review and are not the current test inventory.

The overview belongs in SearXNG's result column. Its primary job is to help a
reader understand an answer, inspect its evidence, and ask a follow-up while
keeping ordinary results easy to reach.

## Findings and changes

| Finding | Change |
| --- | --- |
| The original centered “More” treatment needed polish. | Preserve it per user preference, with divider lines, a consistent chevron, and a compact 36px pill. Keep follow-ups hidden until expansion, including for short answers; “Less” restores the compact view. |
| Multiple sources from the same site produced identical domain pills. | Use one expandable source row with a source count and unique domains. Retain per-answer numbered citations and source snippets. |
| The answer did not explain that its evidence was limited to snippets. | Add “Based on search snippets” below the heading. |
| Copied citations lost their brackets. | Preserve bracketed citation numbers and include follow-up questions when copying a conversation. Keep confirmation screen-reader-only per user preference, avoiding extra text and layout movement. |
| Unicode toolbar icons varied by font, and toolbar targets measured about 40px in the host theme. | Use consistent inline SVG icons and a minimum 44px toolbar target. |
| Escape moved focus out of the follow-up field, including through SearXNG's global keyboard handler. | Contain Escape within the panel. Dismiss open options/settings and return focus to their trigger; otherwise preserve focus. |
| Keyboard navigation could reach citations in visually clipped answer text. | Expand the answer when a citation receives keyboard focus. |

## Visual direction

Keep the host sans-serif and left-aligned result column. Use the host's text,
background, link, and border colors, with fallbacks of paper `#ffffff`, ink
`#222222`, secondary text `#62666d`, divider `#dadde2`, and search blue `#3050ff`.
Derive a pale citation background from the active theme. Answer text has a
72-character maximum measure, a 1rem size matching the host body scale, and a
1.65 line height.

Preserve the original sparkle beside AI Summary and the centered pill disclosure.

The distinctive element is the connection between numbered answer references
and inspectable search snippets. A separate display typeface, decorative card,
and repeated source pills would compete with the surrounding search results.
Limit animation to opening options and settings; honor reduced motion.

## Verification and limits

- Reviewed screenshots in the real Simple theme, including desktop and mobile
  dark mode, using the local fixture instance on port 8899.
- Browser checks cover citations, model changes, follow-ups, copy feedback and
  citation formatting, Escape behavior, long-answer disclosure, keyboard access
  to clipped citations, 320px overflow, reduced motion, errors, retry, and Stop.
- `make check` passes: Ruff lint/format, ty, and 58 unit tests.

This pass verifies the interface with fixture responses. It does not evaluate
live answer quality or validate additional provider/model combinations. Model
output remains plain text with validated numeric citations; richer formatting
would require a separate rendering and security review.

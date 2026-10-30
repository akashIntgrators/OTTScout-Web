# OTTScout identity

The approved identity is the rounded double-ring mark selected on 31 October 2026 (concept v14). The rings and central stem use mint `#8BE0C3` on navy `#10161D`.

`assets/ottscout-mark.svg` is the transparent vector master. Use it for visible website branding; readable OTTScout text remains beside the decorative image. `assets/ottscout-icon.svg` places the same geometry on navy for browsers and home screens. The production assets use solid colours and clean vector contours, following the approved concept without its generated texture.

## Generated website assets

Run `npm ci` and `npm run brand:assets` after changing the master. This produces:

- `assets/ottscout-icon.svg` and `assets/ottscout-icon.png` (512 square).
- `assets/ottscout-icon-192.png` and `assets/ottscout-touch-icon.png` (180 square).
- `favicon.ico` with 16, 32 and 48 pixel images.
- `assets/ottscout-social.svg` and `assets/ottscout-social.png` (1200 × 630).

Only the SVG master needs editing. Generated assets are committed so deployment does not require the renderer. Browser-facing URLs use `?v=brand14` to refresh old cached artwork. Increment that version in the dashboard and shared generated-page template when intentionally changing the identity.

## Phone and TV project

The separate local `OTTScout-Apps` project keeps an identical copy of the master at `assets/brand-mark.svg`. Copy the website master there before running its `npm run brand:assets`. Its generator creates a 1024 pixel app icon, a transparent adaptive foreground within Android's safe area, a transparent screen mark, a splash image and the 320 × 180 TV launcher banner. App configuration and screen headers consume those assets.

## Publication

Use the manual **Publish OTTScout website** workflow for visual changes. It reuses the last published catalogue, checks the project, and publishes Pages without consuming streaming-provider or TMDB requests. The existing scheduled collector remains responsible for availability updates.

Changes cover the live dashboard and all generated weekly, language, title, guide and informational pages. The `dist/` folder is an archived early prototype and is not published by the current build. Native APKs are test builds; Apple and app-store releases remain separate work.

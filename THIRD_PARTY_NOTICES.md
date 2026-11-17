# Third-Party Notices

The resume shows the logos of the employers and schools it lists. Apple devices set its text in
their own system font, which the site never ships; every other device gets one self-hosted font.
Each icon and the font below name their source, pinned to the version that was fetched, and their
license. The icon license texts that require attribution follow in full; the font's license ships
next to the font file.

Each slug is `public/img/icons/<slug>.svg`, except `nyu` and `stonybrook`: they are 96×96 PNG
fallbacks, because no usable vector source was found. `favicon` is `public/favicon.ico` and
`apple-touch-icon` is `public/apple-touch-icon.png`. Every SVG was normalized to the shared
`0 0 24 24` viewBox; other changes are noted in the table.

## Icons

| Slug             | Source, pinned version                                                                                         | License                                           |
| ---------------- | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| addepar          | <https://cdn.jsdelivr.net/gh/Addepar/ember-charts@gh-pages/img/addepar_logo_horz.svg>, mark only, filled black | [BSD-3-Clause](#bsd-3-clause-license-addepar-inc) |
| amazon           | <https://cdn.jsdelivr.net/npm/simple-icons@14.15.0/icons/amazon.svg>, two-tone brand fills                     | [CC0-1.0](#cc0-sources)                           |
| apple            | <https://cdn.jsdelivr.net/npm/simple-icons@16.37.0/icons/apple.svg>                                            | [CC0-1.0](#cc0-sources)                           |
| aws              | <https://cdn.jsdelivr.net/gh/gilbarbara/logos@b9edc65f8946/logos/aws.svg>                                      | [CC0-1.0](#cc0-sources)                           |
| ebay             | <https://cdn.jsdelivr.net/npm/@iconify-json/thesvg-color@1.2.27/icons.json>, icon `ebay`                       | [MIT](#mit-license-thesvgorg)                     |
| microsoft        | <https://cdn.jsdelivr.net/gh/gilbarbara/logos@b9edc65f8946/logos/microsoft-icon.svg>, Microsoft brand fills    | [CC0-1.0](#cc0-sources)                           |
| nyu              | <https://resume.chenyang.us/favicon.ico>, raster served by the site before the migration                       | Not openly licensed; New York University mark     |
| roblox           | <https://cdn.jsdelivr.net/npm/simple-icons@16.37.0/icons/roblox.svg>                                           | [CC0-1.0](#cc0-sources)                           |
| stonybrook       | <https://resume.chenyang.us/stonybrook.ico>, raster served by the site before the migration                    | Not openly licensed; Stony Brook University mark  |
| walmart          | <https://cdn.jsdelivr.net/npm/@iconify-json/thesvg@1.2.15/icons.json>, icon `walmart`, Spark Yellow fill       | [MIT](#mit-license-thesvgorg)                     |
| yahoo            | <https://cdn.jsdelivr.net/npm/simple-icons@9.21.0/icons/yahoo.svg>                                             | [CC0-1.0](#cc0-sources)                           |
| favicon          | <https://resume.chenyang.us/favicon.ico>, same source as `nyu`                                                 | Not openly licensed; New York University mark     |
| apple-touch-icon | <https://resume.chenyang.us/favicon.ico>, same source as `nyu`                                                 | Not openly licensed; New York University mark     |

## Fonts

| File                                             | Source, pinned version                                                                                      | License                                        |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `public/fonts/noto-sans-latin-wght-normal.woff2` | <https://cdn.jsdelivr.net/npm/@fontsource-variable/noto-sans@5.3.0/files/noto-sans-latin-wght-normal.woff2> | [OFL-1.1](#sil-open-font-license-11-noto-sans) |

Noto Sans by the Noto Project Authors, font version 2.015: the Latin roman subset with the `wght`
axis (100–900), from `@fontsource-variable/noto-sans@5.3.0`. The file ships exactly as published:
35,820 bytes, SHA-256 `51ca196f49a33e79e7870ff88ebd2829a3f627a51e7d690986618f0e7ad2b52d`.

## CC0 sources

These sources dedicate their artwork to the public domain under
[CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/). No attribution is required;
they are listed for provenance.

- [Simple Icons](https://github.com/simple-icons/simple-icons): `simple-icons@9.21.0` (yahoo),
  `simple-icons@14.15.0` (amazon), and `simple-icons@16.37.0` (apple, roblox). License text:
  <https://cdn.jsdelivr.net/npm/simple-icons@16.37.0/LICENSE.md>.
- [gilbarbara/logos](https://github.com/gilbarbara/logos) at commit `b9edc65f8946` (aws, microsoft).
  License text: <https://cdn.jsdelivr.net/gh/gilbarbara/logos@b9edc65f8946/LICENSE.txt>.

## MIT License (thesvg.org)

Covers `ebay` (`@iconify-json/thesvg-color@1.2.27`) and `walmart` (`@iconify-json/thesvg@1.2.15`).
Both icon sets name <https://github.com/glincker/thesvg/blob/main/LICENSE> as their license.

```text
MIT License

Copyright (c) 2025 thesvg.org

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## BSD-3-Clause License (Addepar, Inc.)

Covers `addepar`, taken from the Addepar/ember-charts repository. License text:
<https://cdn.jsdelivr.net/gh/Addepar/ember-charts@3.0.2/LICENSE.md>.

```text
Copyright (c) 2012 Addepar, Inc. All Rights Reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
this list of conditions and the following disclaimer in the documentation
and/or other materials provided with the distribution.

3. "Addepar" or "Addepar, Inc." may not be used to endorse or promote products
derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY ADDEPAR, INC. "AS IS" AND ANY EXPRESS OR IMPLIED
WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO
EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT
OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY
OF SUCH DAMAGE.
```

## SIL Open Font License 1.1 (Noto Sans)

Covers `public/fonts/noto-sans-latin-wght-normal.woff2`. Upstream project:
<https://github.com/notofonts/latin-greek-cyrillic>. The copyright notice in the font file reads:

```text
Copyright 2022 The Noto Project Authors (https://github.com/notofonts/latin-greek-cyrillic)
```

That notice and the full license text ship next to the font as `public/fonts/OFL.txt`, served at
<https://resume.chenyang.us/fonts/OFL.txt>.

## Trademarks

All logos remain trademarks of their respective owners and are used only to identify the employers and schools listed in the resume.

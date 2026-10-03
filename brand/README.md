# VigyanBytes brand packs (branch `vigyan-brand` only)

This branch adds two theme packs to the neutral fork: `vigyan-ivory` (the default
ground) and `vigyan-deep` (for an LCD inside a dark case frame). `master` never
carries them; changes flow master -> vigyan-brand only (`git rebase master`).

Regenerate after a brand revision:

    uv run --with cairosvg python brand/build_brand_packs.py \
        --brand-dir ../vigyanbytes-web/docs/brand

The script:

- reads the colours from `tokens.css`, so no hex value is typed by hand;
- copies Newsreader 600, Public Sans 700 and 400, and JetBrains Mono 500, together
  with their SIL OFL licence;
- rasterises `mark-small-*` for the corner mark (drawn at 32 px or less) and the
  full mandala for a theme's background mode (one centred copy at 5-20 % opacity,
  with the corner mark suppressed);
- checks the built-in designs for emoji and forbidden words;
- warns when text or muted colours fall below 4.5:1 contrast on the ground.

The fleet installer (a19-install-thermalright-aio) uses this branch only when the
operator's llm-cli features include `hw-display-brand`, or when it is run with
`--brand vigyan`.

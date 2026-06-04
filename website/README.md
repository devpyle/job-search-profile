# davidmyers.work — personal site

A portable static website (no build step, no dependencies). Three files do all the work:

- `index.html` — the single-page site (hero, about, experience, skills, education, contact)
- `resume.html` — print-optimized résumé (use the “Save as PDF” button)
- `styles.css` / `script.js` — design system and interactions

Fonts load from Google Fonts; everything else is self-contained.

## Preview locally

```bash
cd website
python3 -m http.server 8000
# open http://localhost:8000
```

## Deploy (pick one — all free)

The site is plain static files, so any static host works. Point the `davidmyers.work`
domain at whichever you choose.

### Cloudflare Pages
1. Push this repo to GitHub.
2. Cloudflare dashboard → Workers & Pages → Create → Pages → connect the repo.
3. Build command: *(none)* · Build output directory: `website`
4. Custom domains → add `davidmyers.work` (Cloudflare handles DNS + SSL automatically).

### GitHub Pages
1. Settings → Pages → Source: deploy from branch, folder `/website` (or move files to `/docs`).
2. Add a file named `CNAME` containing `davidmyers.work`.
3. At your registrar, point an `ALIAS`/`A` record per GitHub’s
   [custom domain docs](https://docs.github.com/pages/configuring-a-custom-domain-for-your-github-pages-site).

### Netlify / Vercel
1. Import the repo (or drag-and-drop the `website/` folder onto Netlify).
2. Build command: *(none)* · Publish directory: `website`
3. Add the custom domain `davidmyers.work` in the dashboard and follow the DNS prompts.

## Updating content

The site mirrors the source-of-truth in `../docs/`. When a job entry or skill changes
there, update the matching section in `index.html` and `resume.html`.
Keep résumé bullets plain text (no bold), consistent with the project’s resume rules.

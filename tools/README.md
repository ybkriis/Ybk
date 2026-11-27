# tools

Upstream open-source projects linked as git submodules.

| Folder | Upstream | What it does |
|---|---|---|
| `yt-dlp/` | https://github.com/yt-dlp/yt-dlp | Download videos/audio from YouTube and many other sites |
| `clipsai/` | https://github.com/ClipsAI/clipsai | Turn long videos into short clips (transcribe, find clips, auto-reframe) |
| `postiz-app/` | https://github.com/gitroomhq/postiz-app | Self-hosted social media scheduler/publisher |

Pipeline idea: **yt-dlp** downloads → **clipsai** cuts shorts → **postiz** schedules posts.

## Getting the code after cloning this repo

```bash
git clone --recurse-submodules <this-repo>
# or, in an existing clone:
git submodule update --init --recursive
```

## Updating to the latest upstream

```bash
git submodule update --remote tools/yt-dlp tools/clipsai tools/postiz-app
git commit -am "Bump tools submodules"
```

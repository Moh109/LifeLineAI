// Shown on the static demo site (npm run build). Fill in DEMO_VIDEO_URL when the video is up.
export const REPO_URL = 'https://github.com/Moh109/LifeLineAI'
export const DEMO_VIDEO_URL = '' // e.g. 'https://youtu.be/...'

export default function DemoBanner() {
  return (
    <div className="demo-banner" role="note">
      <p>
        <strong>Demo with sample data.</strong> The Lifeline voice line was live during CodeRED Orion (Oct 2026).
        Every case here is made up, and changes stay in your browser.
      </p>
      <p className="demo-links">
        <a href={REPO_URL} target="_blank" rel="noreferrer">Code on GitHub</a>
        {DEMO_VIDEO_URL
          ? <a href={DEMO_VIDEO_URL} target="_blank" rel="noreferrer">Watch the demo video</a>
          : <span className="muted">Demo video coming soon</span>}
      </p>
    </div>
  )
}

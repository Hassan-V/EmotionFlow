# Google Meet developer deployment

1. Set `NEXT_PUBLIC_GOOGLE_MEET_PROJECT_NUMBER` to the numeric Google Cloud project number before building the frontend.
2. Enable **Google Workspace Marketplace SDK** and **Google Workspace add-ons API** in that project.
3. Create a Meet add-on deployment and paste `deployment.json` as its manifest.
4. Install the unpublished developer add-on using its deployment/install link.
5. Open a Meet call, choose Activities, open EmotionFlow, sign in, and grant microphone permission.

The add-on analyzes only the consenting local participant's microphone. It does not claim access to meeting-wide audio.

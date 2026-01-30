# Production issues(Works but not scalable or not best practice):
Secrets should come from secret manager. Currently they are in backend env
Sql is better than firestore for storing fixed data types. We use firestore because google gives free credits
Audio is a free service. So mechanical. Paid apis sound better
Cancelling meeting is not added as a feature. Once confirmed and scheduled, the AI wont cancel meets.

# How to run hosted service:
Hosted at: https://llm-tools-frontend.vercel.app/
Test users can login. Not all emails have access. To get access contact Arka

# How to run locally:
## Have these in your env:
export NEXT_PUBLIC_API_BASE_URL=http://localhost:8080/
export GOOGLE_CLIENT_ID=YOUR GOOGLE CLIENT ID
export GOOGLE_CLIENT_SECRET=YOUR GOOGLE CLIENT SECRET
export GOOGLE_REDIRECT_URI=http://localhost:8080/auth/google/callback
export OPENAI_API_KEY=YOUR OPENAI API KEY
export FIREBASE_PROJECT_ID=Firebase Project ID
export FIREBASE_PRIVATE_KEY_ID=Firebase Private Key ID
export FIREBASE_PRIVATE_KEY=Firebase Private Key
export FIREBASE_CLIENT_EMAIL=Firebase Client Email
export FIREBASE_CLIENT_ID=Firebase Client Id
export FIREBASE_AUTH_URI=https://accounts.google.com/o/oauth2/auth
export FIREBASE_TOKEN_URI=https://oauth2.googleapis.com/token
export FIREBASE_AUTH_PROVIDER_X509_CERT_URL=https://www.googleapis.com/oauth2/v1/certs
export FIREBASE_CLIENT_X509_CERT_URL=FIREBASE CLIENT X509 CERT URL
export FIREBASE_UNIVERSE_DOMAIN=googleapis.com

## Go to backend directory and run the following:
pip install --no-cache-dir -r requirements.txt
cd app
uvicorn app.main:app --host 0.0.0.0 --port 8080

## Go to frontend directory and run the following:
npm i
npm run dev
Open localhost:3000
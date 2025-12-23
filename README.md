# gcloud-notion-service


bash
gcloud secrets create NOTION_API_KEY
gcloud secrets versions add NOTION_API_KEY

deploy
gcloud functions deploy sync_tasks \
  --gen2 \
  --runtime python311 \
  --region us-west1 \
  --entry-point sync_tasks \
  --trigger-http \
  --allow-unauthenticated=false \
  --set-env-vars NOTION_DB_ID=xxxx

schedule 
gcloud scheduler jobs create http tasks-to-notion \
  --schedule="0 6 * * *" \
  --uri=FUNCTION_URL \
  --http-method=GET \
  --oidc-service-account-email=tasks-notion-sync@PROJECT.iam.gserviceaccount.com

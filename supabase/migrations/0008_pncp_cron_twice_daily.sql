create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net with schema extensions;

select cron.unschedule(jobid)
from cron.job
where jobname = 'licita-ai-pncp-sync';

select cron.schedule(
  'licita-ai-pncp-sync',
  '0 */12 * * *',
  $job$
    select net.http_post(
      url := 'https://licita-ai-syrd.onrender.com/api/internal/sync-pncp',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'X-PNCP-Sync-Secret', (
          select decrypted_secret
          from vault.decrypted_secrets
          where name = 'licita_ai_pncp_sync'
        )
      ),
      body := '{}'::jsonb,
      timeout_milliseconds := 180000
    );
  $job$
);

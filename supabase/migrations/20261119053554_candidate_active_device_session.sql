-- Soft single-device session lock for the candidate portal.
-- active_device_id + session_last_seen_at let OTP login reject a second device
-- while the first device was seen within the last few minutes.

alter table public.candidates
    add column if not exists active_device_id varchar(64) null,
    add column if not exists session_last_seen_at timestamptz null;

comment on column public.candidates.active_device_id is
    'Stable X-Device-Id of the device that currently holds the candidate portal session.';
comment on column public.candidates.session_last_seen_at is
    'Last authenticated portal request (or successful login); used for soft session expiry.';

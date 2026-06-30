# Troubleshooting

## YouTube Blocks Anonymous Access

Symptoms: yt-dlp reports sign-in, bot check, rate limit, or unavailable anonymous access.

Actions:

- Update yt-dlp from diagnostics or restart the add-on.
- Wait and retry later.
- Try a public, non-private URL.
- Do not publish cookies, tokens, private URLs, or account data in issue reports.

This project does not support bypassing provider access controls or using login cookies.

## No Disk Space

Symptoms: job error code `NO_DISK_SPACE`, failed thumbnail writes, or Home Assistant low-space notification.

Actions:

- Delete old downloaded files from the UI.
- Check the storage card on the start page.
- Verify the configured storage has free space.
- Collect job details, diagnostics page output, and add-on logs.

## NFS Detached

Symptoms: startup fails, write test fails, or files disappear after storage reconnects.

Actions:

- Confirm the Home Assistant network storage is mounted.
- Check `/media/...` or `/share/...` target path in diagnostics.
- Restart the add-on after the mount is available.
- Collect diagnostics and Home Assistant supervisor logs.

## ffmpeg Does Not Generate Thumbnails

Symptoms: download completes but video thumbnail is missing or a thumbnail warning is shown.

Actions:

- Open diagnostics and verify `ffmpeg -version` works.
- Check job logs for ffmpeg stderr.
- Confirm the file is a supported video and not a partial file.
- Source thumbnails may still appear if yt-dlp metadata included one.

## Live Does Not Start

Symptoms: live job stays `waiting`, fails as source unavailable, or stops immediately.

Actions:

- Verify the stream is actually live or upcoming.
- Check job logs for yt-dlp live status.
- Use diagnostics to verify network and yt-dlp.
- Stop duplicate live jobs for the same URL before retrying.

## Home Assistant Ingress Does Not Work

Symptoms: links open without the Ingress prefix or show 404 behind Home Assistant.

Actions:

- Open the add-on through Home Assistant Ingress, not only the mapped port.
- Check browser developer tools for wrong paths.
- Include the diagnostics page and the failing path in reports.
- Do not include tokens from Ingress URLs.

## yt-dlp Update Does Not Work

Symptoms: diagnostics shows last update error or old yt-dlp behavior remains.

Actions:

- Check add-on logs for pip/network errors.
- Confirm outbound network access from the add-on.
- Restart the add-on to retry startup update.
- Include sanitized update logs in reports.

## Collect Diagnostics Without Secrets

Collect:

- Diagnostics page rows.
- Job details page and full job log.
- Add-on logs around the failure.
- Home Assistant supervisor logs for storage/API issues.
- Error code, status, storage name, and platform tag.

Do not publish:

- Home Assistant tokens.
- Cookies.
- Private URLs.
- Full URLs containing secrets or signed query parameters.
- NFS credentials.

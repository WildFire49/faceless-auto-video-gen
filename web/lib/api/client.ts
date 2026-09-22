/**
 * The Connect client.
 *
 * This is the web app's composition root (SPEC.md 14.1, rule 3): the only
 * module that names a transport or a base URL. Everything else imports the
 * typed client from here.
 *
 * Note there are no hand-written request or response interfaces anywhere in
 * this app -- they are generated from proto/ into lib/gen, so the dashboard
 * cannot drift from the Go API (SPEC.md 3.3).
 */

import { createClient, type Client } from '@connectrpc/connect';
import { createConnectTransport } from '@connectrpc/connect-web';

import { RewindService } from '@/lib/gen/rewind/v1/api_pb';
import { FactsService } from '@/lib/gen/rewind/v1/facts_pb';
import { VideoService } from '@/lib/gen/rewind/v1/video_pb';

/**
 * Where the Go API lives. Mirrors `web.api_base_url` in config/services.yaml;
 * the env var lets a developer point at a different port without editing code.
 */
const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8080';

/**
 * Connect speaks plain JSON over HTTP here, because browsers cannot speak
 * native gRPC. The Go server exposes the same service over real gRPC to the
 * Python worker from the identical proto definition (SPEC.md 2.5).
 */
const transport = createConnectTransport({
  baseUrl,
  // JSON rather than binary: it costs a little bandwidth on localhost and buys
  // readable payloads in devtools, which matters far more while building.
  useBinaryFormat: false,
});

export const rewindClient: Client<typeof RewindService> = createClient(RewindService, transport);

/** The queue and the six review gates. */
export const videoClient: Client<typeof VideoService> = createClient(VideoService, transport);

/** Gate A: the researched fact sheet. */
export const factsClient: Client<typeof FactsService> = createClient(FactsService, transport);

export { baseUrl as apiBaseUrl };

function corsHeaders(origin) {
	return {
		"Access-Control-Allow-Origin": origin,
		"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
		"Access-Control-Allow-Headers": "Content-Type, Authorization",
	};
}

export default {
	async fetch(request, env, ctx) {
		const ALLOWED_ORIGIN = "https://saa-ssender-sale.vercel.app";
		const origin = request.headers.get("Origin");

		// 🔒 Origin restriction
		if (origin !== ALLOWED_ORIGIN) {
			return new Response("Forbidden", { status: 403 });
		}

		// Preflight (CORS)
		if (request.method === "OPTIONS") {
			return new Response(null, {
				headers: corsHeaders(ALLOWED_ORIGIN),
			});
		}

		try {
			// 🔑 Authorize with Backblaze B2
			const authRes = await fetch("https://api.backblazeb2.com/b2api/v2/b2_authorize_account", {
				headers: {
					Authorization: "Basic " + btoa(`${env.B2_KEY_ID}:${env.B2_APPLICATION_KEY}`),
				},
			});

			if (!authRes.ok) {
				const errText = await authRes.text();
				return new Response(`B2 auth failed: ${errText}`, {
					status: 502,
					headers: corsHeaders(ALLOWED_ORIGIN),
				});
			}

			const auth = await authRes.json();
			const apiUrl = auth.apiUrl;
			const authToken = auth.authorizationToken;
			const downloadUrl = auth.downloadUrl;
			const bucketId = env.B2_BUCKET_ID;

			const url = new URL(request.url);

			// ─── UPLOAD ────────────────────────────────────────────────────────────
			if (url.pathname === "/upload" && request.method === "POST") {
				const filename = url.searchParams.get("filename");
				if (!filename) {
					return new Response("Missing filename", {
						status: 400,
						headers: corsHeaders(ALLOWED_ORIGIN),
					});
				}

				// Get upload URL from B2
				const uploadUrlRes = await fetch(`${apiUrl}/b2api/v2/b2_get_upload_url`, {
					method: "POST",
					headers: {
						Authorization: authToken,
						"Content-Type": "application/json",
					},
					body: JSON.stringify({ bucketId }),
				});

				if (!uploadUrlRes.ok) {
					const errText = await uploadUrlRes.text();
					return new Response(`Failed to get B2 upload URL: ${errText}`, {
						status: 502,
						headers: corsHeaders(ALLOWED_ORIGIN),
					});
				}

				const uploadData = await uploadUrlRes.json();
				const fileBytes = await request.arrayBuffer();

				// Upload file to B2
				const uploadRes = await fetch(uploadData.uploadUrl, {
					method: "POST",
					headers: {
						Authorization: uploadData.authorizationToken,
						"Content-Type": "application/pdf",
						"X-Bz-File-Name": encodeURIComponent(filename),
						"X-Bz-Content-Sha1": "do_not_verify",
					},
					body: fileBytes,
				});

				if (!uploadRes.ok) {
					const errText = await uploadRes.text();
					return new Response(`B2 upload failed: ${errText}`, {
						status: 502,
						headers: corsHeaders(ALLOWED_ORIGIN),
					});
				}

				return new Response(JSON.stringify({ ok: true, key: filename }), {
					headers: {
						...corsHeaders(ALLOWED_ORIGIN),
						"Content-Type": "application/json",
					},
				});
			}

			// ─── DOWNLOAD ──────────────────────────────────────────────────────────
			if (url.pathname === "/download" && request.method === "GET") {
				const filename = url.searchParams.get("filename");
				if (!filename) {
					return new Response("Missing filename", {
						status: 400,
						headers: corsHeaders(ALLOWED_ORIGIN),
					});
				}

				const downloadRes = await fetch(
					`${downloadUrl}/file/${env.B2_BUCKET_NAME}/${encodeURIComponent(filename)}`,
					{
						headers: { Authorization: authToken },
					}
				);

				if (!downloadRes.ok) {
					return new Response("File not found", {
						status: downloadRes.status,
						headers: corsHeaders(ALLOWED_ORIGIN),
					});
				}

				const contentType = downloadRes.headers.get("Content-Type") || "application/octet-stream";
				const body = await downloadRes.arrayBuffer();

				return new Response(body, {
					headers: {
						...corsHeaders(ALLOWED_ORIGIN),
						"Content-Type": contentType,
						"Content-Disposition": `attachment; filename="${filename.split("/").pop()}"`,
					},
				});
			}

			// ─── LIST ──────────────────────────────────────────────────────────────
			if (url.pathname === "/list" && request.method === "POST") {
				const listRes = await fetch(`${apiUrl}/b2api/v2/b2_list_file_names`, {
					method: "POST",
					headers: {
						Authorization: authToken,
						"Content-Type": "application/json",
					},
					body: JSON.stringify({ bucketId, maxFileCount: 1000 }),
				});

				const listData = await listRes.json();
				return new Response(JSON.stringify({ files: listData.files || [] }), {
					headers: {
						...corsHeaders(ALLOWED_ORIGIN),
						"Content-Type": "application/json",
					},
				});
			}

			// ─── DELETE ────────────────────────────────────────────────────────────
			if (url.pathname === "/delete" && request.method === "POST") {
				const body = await request.json();
				const { fileName, fileId } = body;

				if (!fileName || !fileId) {
					return new Response("Missing fileName or fileId", {
						status: 400,
						headers: corsHeaders(ALLOWED_ORIGIN),
					});
				}

				const deleteRes = await fetch(`${apiUrl}/b2api/v2/b2_delete_file_version`, {
					method: "POST",
					headers: {
						Authorization: authToken,
						"Content-Type": "application/json",
					},
					body: JSON.stringify({ fileName, fileId }),
				});

				if (!deleteRes.ok) {
					const errText = await deleteRes.text();
					return new Response(`Delete failed: ${errText}`, {
						status: 502,
						headers: corsHeaders(ALLOWED_ORIGIN),
					});
				}

				return new Response(JSON.stringify({ ok: true }), {
					headers: {
						...corsHeaders(ALLOWED_ORIGIN),
						"Content-Type": "application/json",
					},
				});
			}

			return new Response("Not found", {
				status: 404,
				headers: corsHeaders(ALLOWED_ORIGIN),
			});
		} catch (err) {
			return new Response(`Worker error: ${err.message}`, {
				status: 500,
				headers: corsHeaders(ALLOWED_ORIGIN),
			});
		}
	},
};

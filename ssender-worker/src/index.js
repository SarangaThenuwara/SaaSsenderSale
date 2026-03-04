export default {
	async fetch(request, env, ctx) {
		const origin = "*";

		if (request.method === "OPTIONS") {
			return new Response(null, { headers: corsHeaders(origin) });
		}

		const url = new URL(request.url);
		const pathname = url.pathname;

		// 🔍 DEBUG endpoint — remove after diagnosis
		if (pathname === "/debug") {
			return new Response(JSON.stringify({
				method: request.method,
				pathname,
				url: request.url,
				headers: Object.fromEntries(request.headers.entries()),
				B2_KEY_ID_set: !!env.B2_KEY_ID,
				B2_APPLICATION_KEY_set: !!env.B2_APPLICATION_KEY,
				B2_BUCKET_ID_set: !!env.B2_BUCKET_ID,
			}, null, 2), {
				headers: { ...corsHeaders(origin), "Content-Type": "application/json" },
			});
		}

		try {
			// ── Step 1: Verify env vars are set ──────────────────────────────────
			if (!env.B2_KEY_ID || !env.B2_APPLICATION_KEY || !env.B2_BUCKET_ID) {
				return new Response(
					JSON.stringify({
						error: "Missing B2 environment variables",
						B2_KEY_ID: !!env.B2_KEY_ID,
						B2_APPLICATION_KEY: !!env.B2_APPLICATION_KEY,
						B2_BUCKET_ID: !!env.B2_BUCKET_ID,
					}),
					{ status: 500, headers: { ...corsHeaders(origin), "Content-Type": "application/json" } }
				);
			}

			// ── Step 2: Authorize with B2 ─────────────────────────────────────────
			const authRes = await fetch("https://api.backblazeb2.com/b2api/v2/b2_authorize_account", {
				headers: {
					Authorization: "Basic " + btoa(`${env.B2_KEY_ID}:${env.B2_APPLICATION_KEY}`),
				},
			});

			if (!authRes.ok) {
				const errText = await authRes.text();
				return new Response(
					JSON.stringify({ error: "B2 auth failed", status: authRes.status, detail: errText }),
					{ status: 502, headers: { ...corsHeaders(origin), "Content-Type": "application/json" } }
				);
			}

			const auth = await authRes.json();
			const { apiUrl, authorizationToken: authToken, downloadUrl } = auth;


			// ── UPLOAD ────────────────────────────────────────────────────────────
			if (pathname === "/upload" && request.method === "POST") {
				const fileName = url.searchParams.get("filename");
				if (!fileName) {
					return new Response(JSON.stringify({ error: "Missing filename param" }), {
						status: 400, headers: { ...corsHeaders(origin), "Content-Type": "application/json" },
					});
				}

				// Get B2 upload URL
				const uploadUrlRes = await fetch(`${apiUrl}/b2api/v2/b2_get_upload_url`, {
					method: "POST",
					headers: { Authorization: authToken, "Content-Type": "application/json" },
					body: JSON.stringify({ bucketId: env.B2_BUCKET_ID }),
				});

				if (!uploadUrlRes.ok) {
					const errText = await uploadUrlRes.text();
					return new Response(
						JSON.stringify({ error: "Failed to get B2 upload URL", status: uploadUrlRes.status, detail: errText }),
						{ status: 502, headers: { ...corsHeaders(origin), "Content-Type": "application/json" } }
					);
				}

				const uploadData = await uploadUrlRes.json();
				const file = await request.arrayBuffer();

				if (file.byteLength > 10 * 1024 * 1024) {
					return new Response(JSON.stringify({ error: "File too large (max 10MB)" }), {
						status: 413, headers: { ...corsHeaders(origin), "Content-Type": "application/json" },
					});
				}

				const b2UploadRes = await fetch(uploadData.uploadUrl, {
					method: "POST",
					headers: {
						Authorization: uploadData.authorizationToken,
						"X-Bz-File-Name": encodeURIComponent(fileName),
						"Content-Type": "b2/x-auto",
						"X-Bz-Content-Sha1": "do_not_verify",
					},
					body: file,
				});

				if (!b2UploadRes.ok) {
					const errText = await b2UploadRes.text();
					return new Response(
						JSON.stringify({ error: "B2 upload failed", status: b2UploadRes.status, detail: errText }),
						{ status: 502, headers: { ...corsHeaders(origin), "Content-Type": "application/json" } }
					);
				}

				const uploadResult = await b2UploadRes.json();
				return new Response(JSON.stringify({ ok: true, key: fileName, fileId: uploadResult.fileId }), {
					status: 200, headers: { ...corsHeaders(origin), "Content-Type": "application/json" },
				});
			}

			// ── DOWNLOAD ──────────────────────────────────────────────────────────
			else if (pathname === "/download" && request.method === "GET") {
				const fileName = url.searchParams.get("filename");
				if (!fileName) {
					return new Response(JSON.stringify({ error: "Missing filename param" }), {
						status: 400, headers: { ...corsHeaders(origin), "Content-Type": "application/json" },
					});
				}

				const dlRes = await fetch(`${downloadUrl}/file/ssender/${fileName}`, {
					headers: { Authorization: authToken },
				});

				if (!dlRes.ok) {
					return new Response(JSON.stringify({ error: "File not found", status: dlRes.status }), {
						status: dlRes.status, headers: { ...corsHeaders(origin), "Content-Type": "application/json" },
					});
				}

				const contentType = dlRes.headers.get("Content-Type") || "application/octet-stream";
				return new Response(await dlRes.arrayBuffer(), {
					headers: {
						...corsHeaders(origin),
						"Content-Type": contentType,
						"Content-Disposition": `attachment; filename="${fileName.split("/").pop()}"`,
					},
				});
			}

			// ── LIST ──────────────────────────────────────────────────────────────
			else if (pathname === "/list" && request.method === "GET") {
				const listRes = await fetch(`${apiUrl}/b2api/v2/b2_list_file_names`, {
					method: "POST",
					headers: { Authorization: authToken, "Content-Type": "application/json" },
					body: JSON.stringify({ bucketId: env.B2_BUCKET_ID, maxFileCount: 100 }),
				});

				const listData = await listRes.json();
				return new Response(JSON.stringify({ files: listData.files || [] }), {
					headers: { ...corsHeaders(origin), "Content-Type": "application/json" },
				});
			}

			// ── DELETE ────────────────────────────────────────────────────────────
			else if (pathname === "/delete" && request.method === "POST") {
				const body = await request.json();
				const { fileName, fileId } = body;

				if (!fileName || !fileId) {
					return new Response(JSON.stringify({ error: "Missing fileName or fileId" }), {
						status: 400, headers: { ...corsHeaders(origin), "Content-Type": "application/json" },
					});
				}

				const delRes = await fetch(`${apiUrl}/b2api/v2/b2_delete_file_version`, {
					method: "POST",
					headers: { Authorization: authToken, "Content-Type": "application/json" },
					body: JSON.stringify({ fileName, fileId }),
				});

				if (!delRes.ok) {
					const errText = await delRes.text();
					return new Response(JSON.stringify({ error: "Delete failed", detail: errText }), {
						status: 502, headers: { ...corsHeaders(origin), "Content-Type": "application/json" },
					});
				}

				return new Response(JSON.stringify({ ok: true }), {
					headers: { ...corsHeaders(origin), "Content-Type": "application/json" },
				});
			}

			return new Response(JSON.stringify({ error: "Not Found" }), {
				status: 404, headers: { ...corsHeaders(origin), "Content-Type": "application/json" },
			});

		} catch (err) {
			return new Response(
				JSON.stringify({ error: err.message || "Internal Server Error", stack: err.stack }),
				{ status: 500, headers: { ...corsHeaders(origin), "Content-Type": "application/json" } }
			);
		}
	},
};

function corsHeaders(origin) {
	return {
		"Access-Control-Allow-Origin": origin,
		"Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
		"Access-Control-Allow-Headers": "Content-Type, Authorization",
	};
}

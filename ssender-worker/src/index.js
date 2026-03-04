export default {
	async fetch(request, env, ctx) {
		const origin = "*"; // ✅ allow all origins

		// ✅ Handle CORS preflight
		if (request.method === "OPTIONS") {
			return new Response(null, {
				headers: corsHeaders(origin),
			});
		}

		try {
			// 🔑 Step 1: Authorize with Backblaze B2
			const authRes = await fetch(
				"https://api.backblazeb2.com/b2api/v2/b2_authorize_account",
				{
					headers: {
						Authorization:
							"Basic " +
							btoa(`${env.B2_KEY_ID}:${env.B2_APPLICATION_KEY}`),
					},
				}
			);

			if (!authRes.ok) {
				throw new Error("B2 authorization failed");
			}

			const auth = await authRes.json();

			const apiUrl = auth.apiUrl;
			const authToken = auth.authorizationToken;
			const downloadUrl = auth.downloadUrl;

			const url = new URL(request.url);
			const pathname = url.pathname;

			let b2Response;

			// =========================
			// 📤 UPLOAD FILE
			// =========================
			if (pathname === "/upload" && request.method === "POST") {
				const fileName = url.searchParams.get("filename");

				if (!fileName) {
					return new Response("Missing filename", { status: 400 });
				}

				// Get upload URL
				const uploadUrlRes = await fetch(
					`${apiUrl}/b2api/v2/b2_get_upload_url`,
					{
						method: "POST",
						headers: {
							Authorization: authToken,
							"Content-Type": "application/json",
						},
						body: JSON.stringify({
							bucketId: env.B2_BUCKET_ID,
						}),
					}
				);

				const uploadData = await uploadUrlRes.json();

				const file = await request.arrayBuffer();

				// 🚫 Limit file size (10MB)
				if (file.byteLength > 10 * 1024 * 1024) {
					return new Response("File too large (max 10MB)", {
						status: 413,
					});
				}

				b2Response = await fetch(uploadData.uploadUrl, {
					method: "POST",
					headers: {
						Authorization: uploadData.authorizationToken,
						"X-Bz-File-Name": encodeURIComponent(fileName),
						"Content-Type": "b2/x-auto",
						"X-Bz-Content-Sha1": "do_not_verify",
					},
					body: file,
				});
			}

			// =========================
			// 📥 DOWNLOAD FILE
			// =========================
			else if (pathname === "/download" && request.method === "GET") {
				const fileName = url.searchParams.get("filename");

				if (!fileName) {
					return new Response("Missing filename", { status: 400 });
				}

				b2Response = await fetch(
					`${downloadUrl}/file/ssender/${fileName}`,
					{
						headers: {
							Authorization: authToken,
						},
					}
				);
			}

			// =========================
			// 📄 LIST FILES
			// =========================
			else if (pathname === "/list" && request.method === "GET") {
				b2Response = await fetch(
					`${apiUrl}/b2api/v2/b2_list_file_names`,
					{
						method: "POST",
						headers: {
							Authorization: authToken,
							"Content-Type": "application/json",
						},
						body: JSON.stringify({
							bucketId: env.B2_BUCKET_ID,
							maxFileCount: 100,
						}),
					}
				);
			}

			// =========================
			// ❌ DELETE FILE
			// =========================
			else if (pathname === "/delete" && request.method === "POST") {
				const { fileName, fileId } = await request.json();

				if (!fileName || !fileId) {
					return new Response("Missing fileName or fileId", {
						status: 400,
					});
				}

				b2Response = await fetch(
					`${apiUrl}/b2api/v2/b2_delete_file_version`,
					{
						method: "POST",
						headers: {
							Authorization: authToken,
							"Content-Type": "application/json",
						},
						body: JSON.stringify({
							fileName,
							fileId,
						}),
					}
				);
			}

			// =========================
			// ❌ INVALID ROUTE
			// =========================
			else {
				return new Response("Not Found", { status: 404 });
			}

			// =========================
			// 📦 RETURN RESPONSE
			// =========================
			const data = await b2Response.arrayBuffer();

			return new Response(data, {
				status: b2Response.status,
				headers: {
					...corsHeaders(origin),
					"Content-Type":
						b2Response.headers.get("Content-Type") ||
						"application/json",
				},
			});
		} catch (err) {
			return new Response(
				JSON.stringify({
					error: err.message || "Internal Server Error",
				}),
				{
					status: 500,
					headers: corsHeaders(origin),
				}
			);
		}
	},
};

// =========================
// ✅ CORS HEADERS
// =========================
function corsHeaders(origin) {
	return {
		"Access-Control-Allow-Origin": origin,
		"Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
		"Access-Control-Allow-Headers": "Content-Type, Authorization",
	};
}

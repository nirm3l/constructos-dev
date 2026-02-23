export default {
  async fetch(request, env) {
    const url = new URL(request.url)
    const host = url.hostname.toLowerCase()

    if (host === "constructis.dev" || host === "www.constructis.dev") {
      const destination = new URL(request.url)
      destination.hostname = "constructos.dev"
      destination.protocol = "https:"
      return Response.redirect(destination.toString(), 301)
    }

    return env.ASSETS.fetch(request)
  },
}

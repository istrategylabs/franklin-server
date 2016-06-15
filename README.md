# franklin-server

Python asyncio HTTP server for proxy serving of Franklin S3 deploys.

## Installation

Requires Python 3.5+. Install required packages with pip:

```
pip install -r requirements.txt
```

For local development, copy _env.example_ to _.env_ and edit to set the required environment variables.

## Usage

Use foreman or forego to run the included Procfile, which serves the app with [gunicorn](http://gunicorn.org). Or look at the Procfile and run the command yourself. franklin-server is just an [aiohttp](http://aiohttp.readthedocs.io/en/stable/) application, so run it however you like.

## Configuration

The following environment variables are **required**:

| env | description |
|-----|-------------|
| AWS_KEY | AWS access key |
| AWS_SECRET | AWS secret key |
| AWS_BUCKET | The bucket containing Franklin deployments |
| FRANKLIN_API_URL | URL to Franklin API domain lookup endpoint |


The following environment variables are **optional**:

| env | description |
|-----|-------------|
| HOST\_CACHE\_TTL | Seconds to cache host config, default *120* |
| HOST\_CACHE\_SIZE | Max number of host configs to cache, default *128* |


## Caching

franklin-server will forward the following request headers to S3:

* Cache-Control
* If-Modified-Since
* If-None-Match

By passing these headers, clients will benefit from increased performance when requesting cacheable resources. If S3 responds with *304 Not Modified*, franklin-server will also return a 304.

On the response, franklin-server will forward the following headers from S3 to the client:

* Content-Length
* Last-Modified
* ETag

franklin-server adds a *Cache-Control* header to the response based on the content type of the object. HTML responses will have *max-age* set to **five minutes**. The following content types will have *max-age* set to **one year**:

* CSS, JavaScript, XML, Atom, RSS, manifest
* MP4, WebM
* MP3, audio-only WebM
* JPEG, PJPEG, PNG, GIF, SVG, SVGZ, ICO
* TTF, TTC, OTF, EOT, WOFF, WOFF2

All other responses will have `Cache-Control: no-cache`.

## Error Handling

Except for 200 and 304, all response status codes from S3 will be returned from franklin-server as *404 Not Found*. In some cases, additional information will be included in the response.

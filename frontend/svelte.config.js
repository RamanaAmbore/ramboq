import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  kit: {
    adapter: adapter({
      pages: 'build',
      assets: 'build',
      fallback: 'index.html', // SPA mode — all routes served from index.html
      precompress: false,
    }),
    alias: {
      $lib: './src/lib',
    },
  },
};

export default config;

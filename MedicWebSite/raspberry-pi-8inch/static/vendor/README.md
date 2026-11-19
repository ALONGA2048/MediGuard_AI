Bundled from this repository's installed dependencies for offline QR decoding:

- @zxing/browser 0.2.1, UMD distribution, MIT; see LICENSE-ZXing-browser.txt.
- The UMD includes @zxing/library 0.23.0, Apache-2.0; see LICENSE-ZXing-library.txt.

Source: https://github.com/zxing-js/browser and https://github.com/zxing-js/library
The kiosk does not download code from a CDN. Node is only used on the development
machine to extract prescription-check.ts into workflow.js; the Pi needs no Node.

import { version, author, homepage } from "../../package.json";

// Single source of truth for anything the UI displays about the app itself
// (About page, footer, ...). Bump the version or change the author/
// homepage in package.json - nothing else needs touching.
export const APP_VERSION = version;
export const APP_AUTHOR = author;
export const APP_HOMEPAGE = homepage;
export const APP_COPYRIGHT_YEAR = new Date().getFullYear();

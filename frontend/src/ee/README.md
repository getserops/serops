# SerOps Enterprise — frontend (`src/ee/`)

Licensed under the [SerOps Enterprise License](LICENSE), not the
AGPL-3.0. See `backend/ee/README.md` for the model and the rules.

Each module is a folder with an `index.js` whose default export says what it
adds; `src/utils/edition.js` finds them with `import.meta.glob`. Community
code never imports from here. Delete this directory and the app builds and
runs as the complete Community edition.

```js
export default {
    settingsPages: [{ path: 'license', perm: 'license.manage', label: (t) => t('...'), Component }],
};
```

Translations for a module live next to it and are added with
`i18n.addResourceBundle`, so the Community locale files carry no
Enterprise strings.

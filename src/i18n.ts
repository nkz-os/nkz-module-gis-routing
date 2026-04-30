import { i18n } from '@nekazari/sdk';
import en from './locales/en.json';
import es from './locales/es.json';
import ca from './locales/ca.json';
import eu from './locales/eu.json';
import fr from './locales/fr.json';
import pt from './locales/pt.json';

const NS = 'gis-routing';

function register(): void {
  const add = i18n && 'addResourceBundle' in i18n ? i18n.addResourceBundle : undefined;
  if (typeof add !== 'function') return;
  for (const [lang, res] of Object.entries({ en, es, ca, eu, fr, pt })) {
    add.call(i18n, lang, NS, res, true, true);
  }
}

register();

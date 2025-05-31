# l10n_it_simple_withholding_cassa

Modulo Odoo per la gestione semplificata di Ritenuta d'acconto e Cassa Previdenziale (es. INPS 4%) su offerte e fatture.

## Funzionalità

- Applica la ritenuta d’acconto su fatture clienti e offerte di vendita.
- Applica la Cassa Previdenziale come riga automatica.
- I valori di default sono configurabili nei dati aziendali (`res.company`).
- I dati selezionati nell’offerta vengono copiati automaticamente nella fattura.
- Totali personalizzati visibili su offerte, fatture e portale cliente.
- Report PDF personalizzati per offerte e fatture.

## Installazione

1. Copia la cartella `l10n_it_simple_withholding_cassa` tra gli addons personalizzati di Odoo.
2. Aggiorna la lista dei moduli.
3. Installa il modulo da Apps.

## Configurazione

- Vai su **Impostazioni > Azienda** e abilita le opzioni:
  - "Applica Ritenuta d'acconto di default"
  - "Applica Cassa Previdenziale di default"
- Personalizza le percentuali direttamente su offerte e fatture.

## Utilizzo

- Su ogni offerta o fattura troverai i campi per abilitare/disabilitare ritenuta e cassa e impostare le relative percentuali.
- I totali verranno calcolati automaticamente e mostrati nei report PDF e nel portale cliente.

## Dipendenze

- `account`
- `sale`

## Autore

Clan Informatico

## Licenza

Questo modulo è distribuito sotto licenza GNU AGPL-3.0.
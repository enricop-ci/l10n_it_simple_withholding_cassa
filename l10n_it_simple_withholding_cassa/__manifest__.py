{
    'name': 'Italy - Ritenuta e Cassa Previdenziale Semplificata',
    'version': '18.0.1.0.0',
    'author': 'Clan Informatico',
    'license': 'AGPL-3',
    'category': 'Accounting',
    'summary': 'Aggiunge gestione ritenuta d\'acconto e cassa previdenziale nelle fatture e nelle offerte Odoo',
    'description': '''
        - Applica ritenuta d’acconto nelle fatture clienti e offerte
        - Applica Cassa Previdenziale (es. INPS 4%) come riga automatica
        - I default possono essere definiti nei dati aziendali
        - I dati selezionati nell’offerta vengono copiati nella fattura
    ''',
    'depends': [
        'account',
        'sale',
    ],
    'data': [
        'views/res_company_view.xml',
        'views/account_move_view.xml',
        'views/sale_order_view.xml',
        'views/report_saleorder_template.xml',
        'views/report_invoice_template.xml',
        #'views/report_invoice_inherit.xml',
        #'views/report_invoice_bank_details.xml',    # nuovo
        'views/report_saleorder_bank_details.xml',  # nuovo
        'views/assets.xml',
    ],
    'qweb': [
        'views/portal_sale_order_templates.xml',  # Rimuovi il commento
    ],
    'installable': True,
    'application': False,
}


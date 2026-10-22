"""schema iniziale

Revision ID: 0001
Revises: 
Create Date: 2026-10-22 10:48:58.333972+00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('clienti',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=255), nullable=False),
    sa.Column('alias', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('domini', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('tipo', sa.String(length=32), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('attivo', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clienti')),
    sa.UniqueConstraint('nome', name=op.f('uq_clienti_nome'))
    )
    op.create_table('impostazioni',
    sa.Column('chiave', sa.String(length=100), nullable=False),
    sa.Column('valore', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('chiave', name=op.f('pk_impostazioni'))
    )
    op.create_table('prodotti',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=255), nullable=False),
    sa.Column('alias', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('descrizione', sa.Text(), nullable=False),
    sa.Column('attivo', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prodotti')),
    sa.UniqueConstraint('nome', name=op.f('uq_prodotti_nome'))
    )
    op.create_table('regole',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('codice', sa.String(length=64), nullable=False),
    sa.Column('nome', sa.String(length=255), nullable=False),
    sa.Column('descrizione', sa.Text(), nullable=False),
    sa.Column('soglia_giorni', sa.Integer(), nullable=True),
    sa.Column('gravita', sa.String(length=16), nullable=False),
    sa.Column('attiva', sa.Boolean(), nullable=False),
    sa.Column('parametri', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_regole')),
    sa.UniqueConstraint('codice', name=op.f('uq_regole_codice'))
    )
    op.create_table('sequenze_codici',
    sa.Column('anno', sa.Integer(), nullable=False),
    sa.Column('ultimo', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('anno', name=op.f('pk_sequenze_codici'))
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('nome', sa.String(length=255), nullable=False),
    sa.Column('ruolo', sa.String(length=32), nullable=False),
    sa.Column('attivo', sa.Boolean(), nullable=False),
    sa.Column('google_sub', sa.String(length=64), nullable=True),
    sa.Column('riceve_digest', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('owner_user_id', sa.Integer(), nullable=True),
    sa.Column('attivo', sa.Boolean(), nullable=False),
    sa.Column('token_cifrato', sa.Text(), nullable=True),
    sa.Column('scopes', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('query_filter', sa.String(length=500), nullable=False),
    sa.Column('sync_gmail', sa.Boolean(), nullable=False),
    sa.Column('sync_drive', sa.Boolean(), nullable=False),
    sa.Column('gmail_history_id', sa.String(length=32), nullable=True),
    sa.Column('gmail_last_sync_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('gmail_sync_from', sa.Date(), nullable=True),
    sa.Column('drive_last_sync_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_sync_status', sa.String(length=32), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_accounts_owner_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_accounts'))
    )
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_accounts_email'), ['email'], unique=True)

    op.create_table('pratiche',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('codice', sa.String(length=20), nullable=False),
    sa.Column('titolo', sa.String(length=300), nullable=False),
    sa.Column('descrizione', sa.Text(), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=True),
    sa.Column('prodotto_id', sa.Integer(), nullable=True),
    sa.Column('stato', sa.String(length=32), nullable=False),
    sa.Column('stato_dal', sa.DateTime(timezone=True), nullable=False),
    sa.Column('stato_verifica', sa.String(length=16), nullable=False),
    sa.Column('origine', sa.String(length=16), nullable=False),
    sa.Column('priorita', sa.String(length=16), nullable=False),
    sa.Column('responsabile_user_id', sa.Integer(), nullable=True),
    sa.Column('account_id', sa.Integer(), nullable=True),
    sa.Column('importo_stima', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('importo_offerta', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('importo_ordine', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('importo_fatturato', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('data_apertura', sa.Date(), nullable=False),
    sa.Column('data_scadenza', sa.Date(), nullable=True),
    sa.Column('data_chiusura', sa.Date(), nullable=True),
    sa.Column('riferimenti', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('drive_folder_id', sa.String(length=128), nullable=True),
    sa.Column('drive_folder_url', sa.String(length=500), nullable=True),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('ultimo_evento_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_pratiche_account_id_accounts')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clienti.id'], name=op.f('fk_pratiche_cliente_id_clienti')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name=op.f('fk_pratiche_created_by_user_id_users')),
    sa.ForeignKeyConstraint(['prodotto_id'], ['prodotti.id'], name=op.f('fk_pratiche_prodotto_id_prodotti')),
    sa.ForeignKeyConstraint(['responsabile_user_id'], ['users.id'], name=op.f('fk_pratiche_responsabile_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pratiche'))
    )
    with op.batch_alter_table('pratiche', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pratiche_cliente_id'), ['cliente_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pratiche_codice'), ['codice'], unique=True)
        batch_op.create_index(batch_op.f('ix_pratiche_data_scadenza'), ['data_scadenza'], unique=False)
        batch_op.create_index(batch_op.f('ix_pratiche_prodotto_id'), ['prodotto_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pratiche_stato'), ['stato'], unique=False)
        batch_op.create_index(batch_op.f('ix_pratiche_stato_verifica'), ['stato_verifica'], unique=False)
        batch_op.create_index(batch_op.f('ix_pratiche_ultimo_evento_at'), ['ultimo_evento_at'], unique=False)

    op.create_table('sync_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=True),
    sa.Column('tipo', sa.String(length=16), nullable=False),
    sa.Column('stato', sa.String(length=16), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('contatori', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('errori', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_sync_runs_account_id_accounts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sync_runs'))
    )
    with op.batch_alter_table('sync_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sync_runs_account_id'), ['account_id'], unique=False)

    op.create_table('watched_folders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('drive_folder_id', sa.String(length=128), nullable=False),
    sa.Column('nome', sa.String(length=255), nullable=False),
    sa.Column('ricorsivo', sa.Boolean(), nullable=False),
    sa.Column('attivo', sa.Boolean(), nullable=False),
    sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_watched_folders_account_id_accounts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_watched_folders')),
    sa.UniqueConstraint('account_id', 'drive_folder_id', name=op.f('uq_watched_folders_account_id'))
    )
    with op.batch_alter_table('watched_folders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_watched_folders_account_id'), ['account_id'], unique=False)

    op.create_table('documenti',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('watched_folder_id', sa.Integer(), nullable=True),
    sa.Column('drive_file_id', sa.String(length=128), nullable=False),
    sa.Column('nome', sa.String(length=500), nullable=False),
    sa.Column('mime_type', sa.String(length=255), nullable=False),
    sa.Column('percorso', sa.String(length=1000), nullable=False),
    sa.Column('parent_folder_id', sa.String(length=128), nullable=True),
    sa.Column('web_view_link', sa.String(length=1000), nullable=True),
    sa.Column('dimensione', sa.Integer(), nullable=True),
    sa.Column('modified_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ultimo_autore', sa.String(length=255), nullable=False),
    sa.Column('estratto', sa.Text(), nullable=False),
    sa.Column('tag_codice', sa.String(length=20), nullable=True),
    sa.Column('tipo_documento', sa.String(length=32), nullable=True),
    sa.Column('stato', sa.String(length=16), nullable=False),
    sa.Column('motivo', sa.String(length=500), nullable=False),
    sa.Column('classificazione', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('pratica_id', sa.Integer(), nullable=True),
    sa.Column('link_origine', sa.String(length=16), nullable=True),
    sa.Column('confidenza', sa.Double(), nullable=True),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_documenti_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['pratica_id'], ['pratiche.id'], name=op.f('fk_documenti_pratica_id_pratiche'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['watched_folder_id'], ['watched_folders.id'], name=op.f('fk_documenti_watched_folder_id_watched_folders'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documenti')),
    sa.UniqueConstraint('account_id', 'drive_file_id', name=op.f('uq_documenti_account_id'))
    )
    with op.batch_alter_table('documenti', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_documenti_account_id'), ['account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_documenti_modified_time'), ['modified_time'], unique=False)
        batch_op.create_index(batch_op.f('ix_documenti_pratica_id'), ['pratica_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_documenti_stato'), ['stato'], unique=False)
        batch_op.create_index(batch_op.f('ix_documenti_tag_codice'), ['tag_codice'], unique=False)

    op.create_table('messaggi',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('gmail_message_id', sa.String(length=32), nullable=False),
    sa.Column('gmail_thread_id', sa.String(length=32), nullable=False),
    sa.Column('message_id_header', sa.String(length=500), nullable=True),
    sa.Column('subject', sa.String(length=1000), nullable=False),
    sa.Column('from_email', sa.String(length=255), nullable=False),
    sa.Column('from_name', sa.String(length=255), nullable=False),
    sa.Column('to_emails', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('cc_emails', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('data', sa.DateTime(timezone=True), nullable=False),
    sa.Column('snippet', sa.Text(), nullable=False),
    sa.Column('body_text', sa.Text(), nullable=False),
    sa.Column('labels', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('has_attachments', sa.Boolean(), nullable=False),
    sa.Column('attachments', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('attachments_text', sa.Text(), nullable=False),
    sa.Column('inviato_da_noi', sa.Boolean(), nullable=False),
    sa.Column('tag_codice', sa.String(length=20), nullable=True),
    sa.Column('stato', sa.String(length=16), nullable=False),
    sa.Column('motivo', sa.String(length=500), nullable=False),
    sa.Column('classificazione', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('pratica_id', sa.Integer(), nullable=True),
    sa.Column('link_origine', sa.String(length=16), nullable=True),
    sa.Column('confidenza', sa.Double(), nullable=True),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_messaggi_account_id_accounts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['pratica_id'], ['pratiche.id'], name=op.f('fk_messaggi_pratica_id_pratiche'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messaggi')),
    sa.UniqueConstraint('account_id', 'gmail_message_id', name=op.f('uq_messaggi_account_id'))
    )
    with op.batch_alter_table('messaggi', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_messaggi_account_id'), ['account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_messaggi_data'), ['data'], unique=False)
        batch_op.create_index(batch_op.f('ix_messaggi_from_email'), ['from_email'], unique=False)
        batch_op.create_index(batch_op.f('ix_messaggi_pratica_id'), ['pratica_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_messaggi_stato'), ['stato'], unique=False)
        batch_op.create_index(batch_op.f('ix_messaggi_tag_codice'), ['tag_codice'], unique=False)
        batch_op.create_index('ix_messaggi_thread', ['account_id', 'gmail_thread_id'], unique=False)

    op.create_table('solleciti',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pratica_id', sa.Integer(), nullable=False),
    sa.Column('regola', sa.String(length=64), nullable=False),
    sa.Column('chiave', sa.String(length=100), nullable=False),
    sa.Column('gravita', sa.String(length=16), nullable=False),
    sa.Column('titolo', sa.String(length=300), nullable=False),
    sa.Column('messaggio', sa.Text(), nullable=False),
    sa.Column('dati', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('stato', sa.String(length=16), nullable=False),
    sa.Column('assegnato_user_id', sa.Integer(), nullable=True),
    sa.Column('snooze_fino', sa.Date(), nullable=True),
    sa.Column('aperto_il', sa.DateTime(timezone=True), nullable=False),
    sa.Column('aggiornato_il', sa.DateTime(timezone=True), nullable=False),
    sa.Column('risolto_il', sa.DateTime(timezone=True), nullable=True),
    sa.Column('risolto_da', sa.String(length=16), nullable=True),
    sa.Column('notificato_il', sa.DateTime(timezone=True), nullable=True),
    sa.Column('occorrenze', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['assegnato_user_id'], ['users.id'], name=op.f('fk_solleciti_assegnato_user_id_users')),
    sa.ForeignKeyConstraint(['pratica_id'], ['pratiche.id'], name=op.f('fk_solleciti_pratica_id_pratiche'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_solleciti')),
    sa.UniqueConstraint('chiave', name=op.f('uq_solleciti_chiave'))
    )
    with op.batch_alter_table('solleciti', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_solleciti_pratica_id'), ['pratica_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_solleciti_regola'), ['regola'], unique=False)
        batch_op.create_index(batch_op.f('ix_solleciti_stato'), ['stato'], unique=False)

    op.create_table('eventi',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pratica_id', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.String(length=40), nullable=False),
    sa.Column('data_evento', sa.DateTime(timezone=True), nullable=False),
    sa.Column('titolo', sa.String(length=300), nullable=False),
    sa.Column('descrizione', sa.Text(), nullable=False),
    sa.Column('fonte_tipo', sa.String(length=16), nullable=False),
    sa.Column('fonte_id', sa.String(length=255), nullable=True),
    sa.Column('fonte_url', sa.String(length=1000), nullable=True),
    sa.Column('chiave', sa.String(length=400), nullable=True),
    sa.Column('messaggio_id', sa.Integer(), nullable=True),
    sa.Column('documento_id', sa.Integer(), nullable=True),
    sa.Column('account_id', sa.Integer(), nullable=True),
    sa.Column('importo', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('scadenza', sa.Date(), nullable=True),
    sa.Column('confidenza', sa.Double(), nullable=True),
    sa.Column('stato_verifica', sa.String(length=16), nullable=False),
    sa.Column('dati', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_eventi_account_id_accounts')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name=op.f('fk_eventi_created_by_user_id_users')),
    sa.ForeignKeyConstraint(['documento_id'], ['documenti.id'], name=op.f('fk_eventi_documento_id_documenti'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['messaggio_id'], ['messaggi.id'], name=op.f('fk_eventi_messaggio_id_messaggi'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['pratica_id'], ['pratiche.id'], name=op.f('fk_eventi_pratica_id_pratiche'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_eventi')),
    sa.UniqueConstraint('chiave', name=op.f('uq_eventi_chiave'))
    )
    with op.batch_alter_table('eventi', schema=None) as batch_op:
        batch_op.create_index('ix_eventi_pratica_data', ['pratica_id', 'data_evento'], unique=False)
        batch_op.create_index(batch_op.f('ix_eventi_pratica_id'), ['pratica_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_eventi_stato_verifica'), ['stato_verifica'], unique=False)
        batch_op.create_index(batch_op.f('ix_eventi_tipo'), ['tipo'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('eventi', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_eventi_tipo'))
        batch_op.drop_index(batch_op.f('ix_eventi_stato_verifica'))
        batch_op.drop_index(batch_op.f('ix_eventi_pratica_id'))
        batch_op.drop_index('ix_eventi_pratica_data')

    op.drop_table('eventi')
    with op.batch_alter_table('solleciti', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_solleciti_stato'))
        batch_op.drop_index(batch_op.f('ix_solleciti_regola'))
        batch_op.drop_index(batch_op.f('ix_solleciti_pratica_id'))

    op.drop_table('solleciti')
    with op.batch_alter_table('messaggi', schema=None) as batch_op:
        batch_op.drop_index('ix_messaggi_thread')
        batch_op.drop_index(batch_op.f('ix_messaggi_tag_codice'))
        batch_op.drop_index(batch_op.f('ix_messaggi_stato'))
        batch_op.drop_index(batch_op.f('ix_messaggi_pratica_id'))
        batch_op.drop_index(batch_op.f('ix_messaggi_from_email'))
        batch_op.drop_index(batch_op.f('ix_messaggi_data'))
        batch_op.drop_index(batch_op.f('ix_messaggi_account_id'))

    op.drop_table('messaggi')
    with op.batch_alter_table('documenti', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_documenti_tag_codice'))
        batch_op.drop_index(batch_op.f('ix_documenti_stato'))
        batch_op.drop_index(batch_op.f('ix_documenti_pratica_id'))
        batch_op.drop_index(batch_op.f('ix_documenti_modified_time'))
        batch_op.drop_index(batch_op.f('ix_documenti_account_id'))

    op.drop_table('documenti')
    with op.batch_alter_table('watched_folders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_watched_folders_account_id'))

    op.drop_table('watched_folders')
    with op.batch_alter_table('sync_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sync_runs_account_id'))

    op.drop_table('sync_runs')
    with op.batch_alter_table('pratiche', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_pratiche_ultimo_evento_at'))
        batch_op.drop_index(batch_op.f('ix_pratiche_stato_verifica'))
        batch_op.drop_index(batch_op.f('ix_pratiche_stato'))
        batch_op.drop_index(batch_op.f('ix_pratiche_prodotto_id'))
        batch_op.drop_index(batch_op.f('ix_pratiche_data_scadenza'))
        batch_op.drop_index(batch_op.f('ix_pratiche_codice'))
        batch_op.drop_index(batch_op.f('ix_pratiche_cliente_id'))

    op.drop_table('pratiche')
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_accounts_email'))

    op.drop_table('accounts')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    op.drop_table('sequenze_codici')
    op.drop_table('regole')
    op.drop_table('prodotti')
    op.drop_table('impostazioni')
    op.drop_table('clienti')

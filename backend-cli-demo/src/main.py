import os
import sys
import click
from client.api import ApiClient
from commands.documents import upload_document, get_document_status
from commands.sessions import create_session, submit_retell, advance_chunk
from commands.health import check_health

api_client = ApiClient()

@click.group()
def cli():
    """ADHD Reading Companion CLI"""
    pass

@cli.command()
@click.argument('file_path')
def upload(file_path):
    """Upload a PDF document."""
    response = upload_document(api_client, file_path)
    click.echo(response)

@cli.command()
@click.argument('document_id')
def status(document_id):
    """Get the status of a document."""
    response = get_document_status(api_client, document_id)
    click.echo(response)

@cli.command()
@click.argument('user_id')
def create_session(user_id):
    """Create a reading session."""
    response = create_session(api_client, user_id)
    click.echo(response)

@cli.command()
@click.argument('session_id')
@click.argument('retell_text')
def retell(session_id, retell_text):
    """Submit a retell for a session."""
    response = submit_retell(api_client, session_id, retell_text)
    click.echo(response)

@cli.command()
@click.argument('session_id')
def next_chunk(session_id):
    """Advance to the next chunk in a session."""
    response = advance_chunk(api_client, session_id)
    click.echo(response)

@cli.command()
def health():
    """Check the health of the backend API."""
    response = check_health(api_client)
    click.echo(response)

if __name__ == '__main__':
    cli()
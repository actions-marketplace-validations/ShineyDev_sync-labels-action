import argparse
import asyncio
import pathlib
import re
import sys
import textwrap
import traceback

import aiohttp
import graphql
import yaml
import yarl


_printers = list()


def _create_printer(level, prefix, suffix, *, stream=None):
    def printer(*args, **kwargs):
        if printer.is_active:
            if args and isinstance(args[-1], BaseException):
                e = args[-1]
                args = args[:-1] + (
                    "See the error output below.\n\n"
                    + textwrap.indent(
                        "".join(traceback.format_exception(type(e), e, e.__traceback__)),
                        "    "
                    ),
                )

            file = kwargs.pop("file", stream) or sys.stdout
            sep = kwargs.pop("sep", " ")

            s = prefix + sep.join(o if isinstance(o, str) else repr(o) for o in args) + suffix
            print(s, file=file, **kwargs)

    printer.level = level
    printer.is_active = False

    _printers.append(printer)

    return printer


print_debug = _create_printer(4, "\x1B[38;2;192;255;128m[DEBUG]\x1B[0m ", "")
print_info = _create_printer(3, "\x1B[38;2;128;128;255m[INFO]\x1B[0m ", "")
print_warning = _create_printer(2, "\x1B[38;2;255;192;128m[WARNING]\x1B[0m ", "")
print_error = _create_printer(1, "\x1B[38;2;255;128;128m[ERROR] ", "\x1B[0m", stream=sys.stderr)


_QUERY_REPOSITORY_ID = "query($owner: String!, $name: String!){ repository (owner: $owner, name: $name) { id } }"


async def main(*, path, repository, token):
    print_debug(path, repository)

    if " ghp_" in token:
        print_warning("You shouldn't prefix your token. We'll do that for you.")

        token = token.split(" ", 1)[1]

    if (
        not token.startswith("ghp_")
        or not 40 <= len(token) <= 255
        or not re.match("^[a-zA-Z0-9_]+$", token)
    ):
        print_warning(
            "That doesn't look like a GitHub personal access token. It should start with 'ghp_', "
            "be between 40 and 255 in length, and contain only [a-zA-Z0-9_]. You can generate one "
            "at https://github.com/settings/tokens."
        )

    headers = {
        "Accept": "application/vnd.github.bane-preview+json",
        "Authorization": f"bearer {token}",
        "User-Agent": f"ShineyDev/sync-labels-action @ {repository}",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        client = graphql.client.Client(session=session, url="https://api.github.com/graphql")

        try:
            owner, name = repository.split("/")
        except ValueError as e:
            print_error(
                f"That doesn't look like a repository! It should look similar to "
                f"'ShineyDev/github', not '{repository}'.",
                e
            )

            return 1

        try:
            data = await client.request(_QUERY_REPOSITORY_ID, owner=owner, name=name)
        except graphql.client.ClientResponseError as e:
            if e.response.status == 401:
                message = "That token isn't valid!"
            else:
                message = "The request to fetch your repository's ID failed."

            print_error(message, e)

            return 1

        try:
            repository_id = data["repository"]["id"]
        except KeyError as e:
            print_error(
                "The repository you provided does not exist or the token you provided cannot see "
                "it.",
                e
            )

            return 1

        print_debug(repository_id)

        return 0


async def main_catchall(*args, **kwargs):
    try:
        code = await main(*args, **kwargs)
    except BaseException as e:
        print_error(e)

        code = 1
    finally:
        return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--repository", required=True, metavar="OWNER/NAME")
    parser.add_argument("--token", required=True)
    parser.add_argument("--verbosity", required=True, type=int, metavar="0-4")
    kwargs = vars(parser.parse_args())

    verbosity = kwargs.pop("verbosity")
    for printer in _printers:
        if verbosity >= printer.level:
            printer.is_active = True

    exit(asyncio.run(main_catchall(**kwargs)))

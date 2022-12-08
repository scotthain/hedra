from typing import List, Union
import click
import os



class CLI(click.MultiCommand):

    command_files = {
        'ping': 'ping.py',
        'graph': 'graph.py'
    }

    def list_commands(self, ctx: click.Context) -> List[str]:
        rv = []
        for filename in self.command_files.values():
            rv.append(filename[:-3])
        rv.sort()
        return rv

    def get_command(self, ctx: click.Context, name: str) -> Union[click.Command, None]:
        ns = {}
        print(name)
        command_file = os.path.join(
            os.path.dirname(__file__),
            self.command_files.get(name, 'ping.py')
        )

        with open(command_file) as f:
            code = compile(f.read(), command_file, 'exec')
            eval(code, ns, ns)

        return ns[name]
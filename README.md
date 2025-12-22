# Example plugin app for Alliance Auth - ASMEK Version

This is an example plugin app for [Alliance Auth](https://gitlab.com/allianceauth/allianceauth) (AA) that can be used as starting point to develop custom plugins.
It is a modified version of [allianceauth-example-plugin](https://gitlab.com/ErikKalkoken/allianceauth-example-plugin), that has been modified to hold our preffered setup.
The instructions have been modified to fit our use case.

## Features

- The plugin can be installed, upgraded (and removed) into an existing AA installation using PyInstaller.
- It has it's own menu item in the sidebar.
- It has one view that shows a panel and some text
- Comes with CI pipeline pre-configured

## How to use it

To use this example as basis for your own development just clone it on your dev machine.

You then should rename the app and then you can install it into your AA dev installation.

### Cloning from repo

For this app we are assuming that you have all your AA projects, your virtual environnement and your AA installation under one top folder (e.g. aa-dev).

This should look something like this:

```plain
aa-dev
|- venv/
|- myauth/
|- accounting
|- (other AA projects ...)

```

Then just cd into the top folder (e.g. aa-dev) and clone the repo. You can give the repo a new name right away (e.g. `allianceauth-your-app-name`).
You also want to create a new git repo for it. Finally, enable [pre-commit](https://pre-commit.com) to enable automatic code style checking.

```bash
git clone https://github.com/astrum-mechanica/aa-accounting.git your-app-name
cd your-app-name
rm -rf .git
git init
pre-commit install
npm install # installs dependencies for linting
```

### Renaming the app

Before installing this app into your dev AA you need to rename it to something suitable for your development project. Otherwise you risk not being able to install additional apps that might also be called example.

Here is an overview of the places that you need to edit to adopt the name.

Easiest is to just find & replace `accounting` `aa-accounting` `accounting` or various other combinations, with your new app name in all files listed below.

One small warning about picking names: Python is a bit particular about what special characters are allowed for names of modules and packages. To avoid any pitfalls I would therefore recommend to use only normal characters (a-z) in your app's name unless you know exactly what you are doing.

| Location                                      | Description                                                                            |
| --------------------------------------------- | -------------------------------------------------------------------------------------- |
| `/accounting/`                                | folder name                                                                            |
| `/accounting/templates/accounting/`           | folder name                                                                            |
| `/pyproject.toml`                             | update module name for version import, update package name, update title, author, etc. |
| `/accounting/apps.py`                         | app name                                                                               |
| `/accounting/__init__.py`                     | app name                                                                               |
| `/accounting/auth_hooks.py`                   | menu hook config incl. icon and label of your app's menu item appearing in the sidebar |
| `/accounting/models.py`                       | app name                                                                               |
| `/accounting/urls.py`                         | app name                                                                               |
| `/accounting/views.py`                        | permission name and template path                                                      |
| `/accounting/templates/accounting/base.html`  | Title of your app to be shown in all views and as title in the browser tab             |
| `/accounting/templates/accounting/index.html` | template path                                                                          |
| `/testauth/settings/local.py`                 | app name                                                                               |
| `/.coveragerc`                                | app name                                                                               |
| `/README.md`                                  | clear content                                                                          |
| `/tox.ini`                                    | app name                                                                               |

## Installing into your dev AA

Once you have cloned or copied all files into place and finished renaming the app you are ready to install it to your dev AA instance.

Make sure you are in your venv and still in your app directory. Then install it with pip in editable mode:

```bash
make dev-install
```

Add your app to the Django project by adding the name of your app to INSTALLED_APPS in `settings/local.py`.

## Migrations

Migrations are made using make, inside the app directory

```bash
make migrations
```

Next perform migrations to add your model to the database:

```bash
make migrate
```

## Pre Commit and tests

Run pre commit prior to committing

you only need to install the first time

```bash
make pre-commit-install

make pre-commit-checks
```

you can run tox tests as follows

```bash
make tox-tests
```

## prep for release

This readme should be replaced with a proper readme like README2.md

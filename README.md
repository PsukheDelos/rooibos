# Madison Digial Image Database (MDID)

The [Madison Digital Image Database](http://mdid.org/) is a free, open source media repo aimed at education spaces.
It was created at [James Madison University](http://www.jmu.edu).

## Django 1.6.5 upgrade - clone to a new directory

**Status:** Currently in a "first running" state - will work on an existing mdid3 installation's database, although obvs don't run it against a production database.

**This branch has the potential to mess up the organization of a django 1.2.7 based branch, so it seems best to `git clone` to seperate directory**

I'm currently running it on OS X but I tried to make any settings chenges as generi as possible (I made most if not all directories set relative to PROJECT_ROOT

### notes

1_ Switched static files to the staticfiles app, so a good start for running against an already existing database after setting up your virtualenv is:

    1_ pip install -f requirements.txt
    1_ python manage.py collectstatic
    1_ python manage.py runserver
    
    
1_ Following the newer django convention, moved the main app files to a 'project' directory, and followed (Jeff Knupp's advice)[http://www.jeffknupp.com/blog/2013/12/18/starting-a-django-16-project-the-right-way/] that this is really a 'config' directory, so settings file plus the main urls & wsgi files are in the PROJECT_ROOT/config directory, collected staticfiles are in PROJECT_ROOT/static, and local templates are in PROJECT_ROOT/templates.

1_ 



## why?

http://www.cvedetails.com/vulnerability-list/vendor_id-10199/product_id-18211/Djangoproject-Django.html

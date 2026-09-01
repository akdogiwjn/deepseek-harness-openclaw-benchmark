# W8 direct tool calling versus code mode

A local deterministic provider causes eight sequential shell operations. Each
operation appends one unique marker to `w8.log`. Direct mode exposes eight
model-visible shell calls; code mode exposes one program call containing the
same eight underlying shell operations.
